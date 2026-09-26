import os
from pathlib import Path

# Where the panel stores normalized videos, pending uploads and its database.
VIDEOS_DIR = Path(os.getenv("VIDEOS_DIR", "/videos"))
INCOMING_DIR = VIDEOS_DIR / "incoming"
DB_PATH = Path(os.getenv("DB_PATH", str(VIDEOS_DIR / "panel.sqlite3")))

# Where the same volume is mounted inside the MediaMTX container.
MEDIAMTX_VIDEOS_DIR = os.getenv("MEDIAMTX_VIDEOS_DIR", "/videos").rstrip("/")
MEDIAMTX_API = os.getenv("MEDIAMTX_API", "http://mediamtx:9997").rstrip("/")

# Ports shown to users in the UI (as published on the host).
PUBLIC_RTSP_PORT = int(os.getenv("PUBLIC_RTSP_PORT", "8556"))
PUBLIC_HLS_PORT = int(os.getenv("PUBLIC_HLS_PORT", "8890"))
PUBLIC_WEBRTC_PORT = int(os.getenv("PUBLIC_WEBRTC_PORT", "8891"))
PUBLIC_PLAYBACK_PORT = int(os.getenv("PUBLIC_PLAYBACK_PORT", "8996"))

# Archive (recording) settings, applied per path by mediamtx.path_config().
# The directory is inside the MediaMTX container, on its own writable volume.
RECORD_DIR = os.getenv("RECORD_DIR", "/recordings").rstrip("/")
# Recording is the one thing here that fills a disk. Keep the default short and
# raise it deliberately: 30 cameras at 2 Mbps is ~648 GB/day.
RECORD_RETENTION = os.getenv("RECORD_RETENTION", "6h")
RECORD_SEGMENT_DURATION = os.getenv("RECORD_SEGMENT_DURATION", "10m")

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "4096")) * 1024 * 1024
TRANSCODE_CONCURRENCY = max(1, int(os.getenv("TRANSCODE_CONCURRENCY", "1")))
RECONCILE_INTERVAL = float(os.getenv("RECONCILE_INTERVAL", "15"))

PANEL_USER = os.getenv("PANEL_USER", "")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")
