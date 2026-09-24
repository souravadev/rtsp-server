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

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "4096")) * 1024 * 1024
TRANSCODE_CONCURRENCY = max(1, int(os.getenv("TRANSCODE_CONCURRENCY", "1")))
RECONCILE_INTERVAL = float(os.getenv("RECONCILE_INTERVAL", "15"))

PANEL_USER = os.getenv("PANEL_USER", "")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")
