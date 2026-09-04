"""Batch delivery: push every prepared file in a folder to a profile's device."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .profiles import Profile
from .transfer import make_backend
from .transfer.base import SendItem

EventCb = Callable[[str, dict], None]
StopCb = Callable[[], bool]

MEDIA_EXTS = {".mp4", ".mkv", ".m4v", ".avi", ".mov"}


def collect(folder: str | Path) -> list[Path]:
    folder = Path(folder)
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in MEDIA_EXTS)


def send_batch(profile: Profile, folder: str | Path,
               on_event: EventCb, should_stop: StopCb,
               files: list[Path] | None = None) -> list[SendItem]:
    """Send `files` (or everything in `folder` when None) to the profile's device."""
    paths = list(files) if files is not None else collect(folder)
    items = [SendItem(local=p, name=p.name) for p in paths]
    on_event("send_start", {"count": len(items), "target": profile.name})
    if not items:
        on_event("send_done", {"items": []})
        return items

    backend = make_backend(profile.transfer)
    try:
        backend.connect()
        backend.ensure_dir()
        for it in items:
            if should_stop():
                it.detail = "stopped"
                break
            on_event("send_item_start", {"name": it.name, "size": it.local.stat().st_size})
            try:
                backend.put(it.local, it.name,
                            progress=lambda done, total, n=it.name:
                            on_event("send_progress", {"name": n, "done": done, "total": total}))
                ok, detail = backend.verify(it.local, it.name, profile.verify)
                it.ok, it.detail = ok, detail
            except Exception as e:  # noqa: BLE001
                it.ok, it.detail = False, str(e)
            on_event("send_item_done", {"name": it.name, "ok": it.ok, "detail": it.detail})

        hook_out = ""
        if any(it.ok for it in items):
            try:
                hook_out = backend.run_hook()
            except Exception as e:  # noqa: BLE001
                hook_out = f"hook failed: {e}"
        on_event("send_done", {"items": [vars(i) for i in items], "hook": hook_out})
    finally:
        backend.close()
    return items
