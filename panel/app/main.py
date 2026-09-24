import asyncio
import base64
import logging
import re
import secrets
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.requests import ClientDisconnect

from . import config, db, media, mediamtx, reconciler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("panel")

STREAM_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    db.init()
    media.resume_pending()
    task = asyncio.create_task(reconciler.run_forever())
    yield
    task.cancel()


app = FastAPI(title="RTSP Video Panel", lifespan=lifespan)


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if config.PANEL_USER and request.url.path != "/api/health":
        expected = base64.b64encode(f"{config.PANEL_USER}:{config.PANEL_PASSWORD}".encode()).decode()
        given = request.headers.get("authorization", "").removeprefix("Basic ").strip()
        if not secrets.compare_digest(given, expected):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="RTSP Panel"'})
    return await call_next(request)


def _validate_stream_name(name: str) -> None:
    if not STREAM_NAME_RE.match(name):
        raise HTTPException(422, "Stream name may contain only letters, digits, '-' and '_' (max 64).")


def _unique_stream_name(filename: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(filename).stem).strip("-_").lower()[:56] or "stream"
    taken = {r["stream_name"] for r in db.query("SELECT stream_name FROM videos")}
    name, n = base, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    return name


def _get_or_404(video_id: str) -> dict:
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    return video


async def _apply() -> None:
    """Push DB state to MediaMTX now; the background loop retries on failure."""
    try:
        await reconciler.reconcile_once()
    except Exception as e:
        log.warning("immediate reconcile failed: %s", e)
        reconciler.trigger()


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/config")
async def get_config():
    return {
        "rtsp_port": config.PUBLIC_RTSP_PORT,
        "hls_port": config.PUBLIC_HLS_PORT,
        "webrtc_port": config.PUBLIC_WEBRTC_PORT,
        "max_upload_bytes": config.MAX_UPLOAD_BYTES,
    }


@app.get("/api/videos")
async def list_videos():
    videos = db.query("SELECT * FROM videos ORDER BY created_at DESC")
    try:
        runtime = await mediamtx.list_runtime_paths()
        server_ok = True
    except Exception:
        runtime, server_ok = {}, False
    for v in videos:
        v["enabled"] = bool(v["enabled"])
        rt = runtime.get(v["stream_name"])
        v["live"] = {
            "registered": rt is not None,
            "ready": bool(rt and (rt.get("ready") or rt.get("online"))),
            "readers": len(rt.get("readers") or []) if rt else 0,
        }
    return {"server_ok": server_ok, "videos": videos}


@app.post("/api/videos", status_code=201)
async def upload_video(
    request: Request,
    filename: str = Query(..., min_length=1, max_length=255),
    stream_name: str | None = Query(None),
):
    """Upload a video as the raw request body (streamed straight to disk)."""
    if stream_name:
        _validate_stream_name(stream_name)
        if db.query("SELECT 1 FROM videos WHERE stream_name = ?", (stream_name,)):
            raise HTTPException(409, f"Stream name '{stream_name}' is already in use.")
    length = request.headers.get("content-length")
    if length and int(length) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is too large.")

    video_id = uuid.uuid4().hex
    dest = config.INCOMING_DIR / video_id
    size = 0
    try:
        with dest.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "File is too large.")
                f.write(chunk)
        if size == 0:
            raise HTTPException(400, "Empty upload.")
        try:
            db.execute(
                "INSERT INTO videos (id, original_name, stream_name, file, status, size_bytes)"
                " VALUES (?, ?, ?, ?, 'processing', ?)",
                (video_id, filename, stream_name or _unique_stream_name(filename), f"{video_id}.mp4", size),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Stream name is already in use.")
    except (HTTPException, ClientDisconnect, OSError):
        dest.unlink(missing_ok=True)
        raise

    media.start_normalize(video_id)
    return db.get_video(video_id)


class VideoPatch(BaseModel):
    stream_name: str | None = None
    enabled: bool | None = None
    mode: Literal["on_demand", "always_on"] | None = None


@app.patch("/api/videos/{video_id}")
async def update_video(video_id: str, patch: VideoPatch):
    _get_or_404(video_id)
    fields = patch.model_dump(exclude_none=True)
    if "stream_name" in fields:
        _validate_stream_name(fields["stream_name"])
    if "enabled" in fields:
        fields["enabled"] = int(fields["enabled"])
    if fields:
        try:
            db.update_video(video_id, **fields)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Stream name is already in use.")
        await _apply()
    return db.get_video(video_id)


@app.delete("/api/videos/{video_id}", status_code=204)
async def delete_video(video_id: str):
    video = _get_or_404(video_id)
    db.execute("DELETE FROM videos WHERE id = ?", (video_id,))
    await _apply()
    (config.VIDEOS_DIR / video["file"]).unlink(missing_ok=True)
    (config.INCOMING_DIR / video_id).unlink(missing_ok=True)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
