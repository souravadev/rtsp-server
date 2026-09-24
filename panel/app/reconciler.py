"""Keeps MediaMTX's (in-memory) path config in sync with the panel database."""

import asyncio
import logging

from . import config, db, mediamtx

log = logging.getLogger("panel.reconciler")

_lock = asyncio.Lock()
_wake = asyncio.Event()


async def reconcile_once() -> None:
    async with _lock:
        desired = {
            v["stream_name"]: mediamtx.path_config(v)
            for v in db.query("SELECT * FROM videos WHERE enabled = 1 AND status = 'ready'")
        }
        current = await mediamtx.list_config_paths()

        for name, conf in current.items():
            if name not in desired and mediamtx.is_managed(conf):
                log.info("removing path %s", name)
                await mediamtx.delete_path(name)

        for name, conf in desired.items():
            cur = current.get(name)
            if cur is None:
                log.info("adding path %s", name)
                await mediamtx.add_path(name, conf)
            elif any(cur.get(k) != v for k, v in conf.items()):
                log.info("updating path %s", name)
                await mediamtx.replace_path(name, conf)


def trigger() -> None:
    _wake.set()


async def run_forever() -> None:
    while True:
        _wake.clear()
        try:
            await reconcile_once()
        except Exception as e:
            log.warning("reconcile failed: %s", e)
        try:
            await asyncio.wait_for(_wake.wait(), config.RECONCILE_INTERVAL)
        except TimeoutError:
            pass
