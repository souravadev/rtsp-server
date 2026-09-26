"""Thin client for the MediaMTX v3 control API."""

import httpx

from . import config

_client = httpx.AsyncClient(base_url=config.MEDIAMTX_API, timeout=5)

# Marker present in every path command the panel creates, used to tell
# panel-managed paths apart from anything configured by hand.
MANAGED_MARKER = f" -i {config.MEDIAMTX_VIDEOS_DIR}/"


def _record_config(video: dict) -> dict:
    """Recording keys for one path. Always sent, so turning the archive off takes effect."""
    return {
        "record": bool(video.get("archive")),
        "recordPath": f"{config.RECORD_DIR}/%path/%Y-%m-%d_%H-%M-%S-%f",
        "recordFormat": "fmp4",
        "recordSegmentDuration": config.RECORD_SEGMENT_DURATION,
        "recordDeleteAfter": config.RECORD_RETENTION,
    }


def path_config(video: dict) -> dict:
    cmd = (
        "ffmpeg -hide_banner -loglevel error -re -stream_loop -1"
        f"{MANAGED_MARKER}{video['file']}"
        " -c copy -f rtsp -rtsp_transport tcp rtsp://localhost:$RTSP_PORT/$MTX_PATH"
    )
    # An on-demand path only publishes while someone is watching, so there would be
    # nothing to record between viewers. Archiving therefore implies always-on.
    if video["mode"] == "always_on" or video.get("archive"):
        conf = {"source": "publisher", "runOnInit": cmd, "runOnInitRestart": True, "runOnDemand": ""}
    else:
        conf = {
            "source": "publisher",
            "runOnInit": "",
            "runOnDemand": cmd,
            "runOnDemandRestart": True,
            "runOnDemandStartTimeout": "10s",
            "runOnDemandCloseAfter": "10s",
        }
    return conf | _record_config(video)


def is_managed(conf: dict) -> bool:
    return MANAGED_MARKER in (conf.get("runOnDemand") or "") or MANAGED_MARKER in (conf.get("runOnInit") or "")


async def _items(url: str) -> dict[str, dict]:
    r = await _client.get(url, params={"itemsPerPage": 10000})
    r.raise_for_status()
    return {item["name"]: item for item in r.json().get("items") or []}


async def list_config_paths() -> dict[str, dict]:
    return await _items("/v3/config/paths/list")


async def list_runtime_paths() -> dict[str, dict]:
    return await _items("/v3/paths/list")


async def list_recordings() -> dict[str, dict]:
    """What is actually on disk, per path. Empty when nothing has been archived yet."""
    return await _items("/v3/recordings/list")


async def add_path(name: str, conf: dict) -> None:
    (await _client.post(f"/v3/config/paths/add/{name}", json=conf)).raise_for_status()


async def replace_path(name: str, conf: dict) -> None:
    (await _client.post(f"/v3/config/paths/replace/{name}", json=conf)).raise_for_status()


async def delete_path(name: str) -> None:
    r = await _client.delete(f"/v3/config/paths/delete/{name}")
    if r.status_code != 404:
        r.raise_for_status()
