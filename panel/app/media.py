"""Probing and normalizing uploaded videos into RTSP-friendly MP4 files."""

import asyncio
import json
import logging
from pathlib import Path

from . import config, db, reconciler

log = logging.getLogger("panel.media")

# Streams that can be served as-is with `ffmpeg -c copy` over RTSP.
# B-frames are excluded too: MediaMTX refuses to read them over WebRTC.
COPY_VIDEO_CODECS = {"h264", "hevc"}
COPY_PIX_FMTS = {"yuv420p", "yuvj420p"}
COPY_AUDIO_CODECS = {"aac", "opus"}

_sem = asyncio.Semaphore(config.TRANSCODE_CONCURRENCY)
_tasks: set[asyncio.Task] = set()


async def _run(*args: str) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode, out, err


async def probe(path: Path) -> dict:
    rc, out, err = await _run(
        "ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)
    )
    if rc != 0:
        raise RuntimeError(f"ffprobe failed: {err.decode(errors='replace').strip()[-300:]}")
    return json.loads(out)


def _first(info: dict, kind: str) -> dict | None:
    return next((s for s in info.get("streams", []) if s.get("codec_type") == kind), None)


def _fps(stream: dict) -> float | None:
    num, _, den = (stream.get("avg_frame_rate") or "0/0").partition("/")
    try:
        return round(int(num) / int(den), 3) if int(den) else None
    except ValueError:
        return None


def summarize(info: dict) -> dict:
    v, a = _first(info, "video"), _first(info, "audio")
    duration = info.get("format", {}).get("duration")
    return {
        "video_codec": v and v.get("codec_name"),
        "audio_codec": a and a.get("codec_name"),
        "width": v and v.get("width"),
        "height": v and v.get("height"),
        "fps": v and _fps(v),
        "duration": float(duration) if duration else None,
    }


def _ffmpeg_args(info: dict, src: Path, dst: Path) -> list[str]:
    v, a = _first(info, "video"), _first(info, "audio")
    can_copy = (
        v["codec_name"] in COPY_VIDEO_CODECS
        and v.get("pix_fmt") in COPY_PIX_FMTS
        and v.get("has_b_frames") == 0
        and (a is None or a["codec_name"] in COPY_AUDIO_CODECS)
    )
    args = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"]
    if can_copy:
        args += ["-c", "copy"]
        if v["codec_name"] == "hevc":
            args += ["-tag:v", "hvc1"]
    else:
        args += [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-bf", "0",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2",
        ]
    return args + ["-movflags", "+faststart", str(dst)]


async def _normalize(video_id: str) -> None:
    src = config.INCOMING_DIR / video_id
    dst = config.VIDEOS_DIR / f"{video_id}.mp4"
    tmp = config.VIDEOS_DIR / f".{video_id}.tmp.mp4"
    async with _sem:
        try:
            info = await probe(src)
            if _first(info, "video") is None:
                raise RuntimeError("file has no video stream")
            rc, _, err = await _run(*_ffmpeg_args(info, src, tmp))
            if rc != 0:
                raise RuntimeError(f"ffmpeg failed: {err.decode(errors='replace').strip()[-300:]}")
            tmp.rename(dst)
            fields = summarize(await probe(dst))
            if not db.update_video(video_id, status="ready", error=None, size_bytes=dst.stat().st_size, **fields):
                dst.unlink(missing_ok=True)  # deleted while processing
            log.info("video %s ready", video_id)
        except Exception as e:
            log.warning("video %s failed: %s", video_id, e)
            tmp.unlink(missing_ok=True)
            db.update_video(video_id, status="failed", error=str(e)[-500:])
        finally:
            src.unlink(missing_ok=True)
    reconciler.trigger()


def start_normalize(video_id: str) -> None:
    task = asyncio.create_task(_normalize(video_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def resume_pending() -> None:
    """Restart jobs interrupted by a panel restart."""
    for row in db.query("SELECT id FROM videos WHERE status = 'processing'"):
        if (config.INCOMING_DIR / row["id"]).exists():
            start_normalize(row["id"])
        else:
            db.update_video(row["id"], status="failed", error="upload interrupted")
