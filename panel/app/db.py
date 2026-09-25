import sqlite3
import threading

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id            TEXT PRIMARY KEY,
    original_name TEXT NOT NULL,
    stream_name   TEXT NOT NULL UNIQUE,
    file          TEXT NOT NULL,
    status        TEXT NOT NULL,          -- queued | processing | ready | failed
    error         TEXT,
    video_codec   TEXT,
    audio_codec   TEXT,
    width         INTEGER,
    height        INTEGER,
    fps           REAL,
    duration      REAL,
    size_bytes    INTEGER,
    enabled       INTEGER NOT NULL DEFAULT 1,
    mode          TEXT NOT NULL DEFAULT 'on_demand',  -- on_demand | always_on
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def init() -> None:
    global _conn
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, isolation_level=None)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute(SCHEMA)


def query(sql: str, args: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def execute(sql: str, args: tuple = ()) -> int:
    """Run a write statement and return the number of affected rows."""
    with _lock:
        return _conn.execute(sql, args).rowcount


def get_video(video_id: str) -> dict | None:
    rows = query("SELECT * FROM videos WHERE id = ?", (video_id,))
    return rows[0] if rows else None


def update_video(video_id: str, **fields) -> int:
    cols = ", ".join(f"{k} = ?" for k in fields)
    return execute(f"UPDATE videos SET {cols} WHERE id = ?", (*fields.values(), video_id))
