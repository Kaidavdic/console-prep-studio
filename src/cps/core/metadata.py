"""Fetch a torrent's file list without downloading anything.

Used by the Download tab so the user can see every file in the torrent and tick
the ones to keep before the job starts. The resolved metadata is cached as
`state/<key>.torrent` so the real run picks it up instantly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import settings
from .episode_detect import VIDEO_EXTS, build_episode_list
from .pipeline import job_key
from .torrent_engine import TorrentEngine


class TorrentFile:
    __slots__ = ("index", "path", "size", "is_video", "episode", "number")

    def __init__(self, index: int, path: str, size: int):
        self.index = index
        self.path = path
        self.size = size
        self.is_video = Path(path).suffix.lower() in VIDEO_EXTS
        self.episode: str = ""
        self.number: int | None = None


def fetch_file_list(source: str, timeout: float = 120.0, port: int = 6881,
                    regex: str | None = None,
                    on_status: Callable[[str], None] | None = None) -> list[TorrentFile]:
    def say(m: str) -> None:
        if on_status:
            on_status(m)

    key = job_key(source)
    cache = settings.state_dir() / f"{key}.torrent"
    tmp_save = settings.data_dir() / "downloads"

    eng = TorrentEngine(port=port)
    try:
        say("connecting..." if source.startswith("magnet:") else "reading torrent...")
        t = eng.add(source, tmp_save, None,
                    ti_path=cache if cache.exists() else None, upload_mode=True)
        t.wait_metadata(timeout)
        t.deselect_all()
        raw = t.files()
        pads = t.pad_flags()
        try:
            if not cache.exists():
                cache.write_bytes(t.torrent_file_buf())
        except Exception:  # noqa: BLE001
            pass
        t.remove(delete_files=False)
    finally:
        eng.shutdown()

    # keep the real torrent file index, but hide piece-alignment pad files
    files = [TorrentFile(i, p, s) for i, (p, s) in enumerate(raw)
             if not (i < len(pads) and pads[i])]

    # annotate video files with their detected episode number / label
    vids = build_episode_list([f.path for f in files if f.is_video], regex)
    by_path = {e.src_rel: e for e in vids}
    for f in files:
        e = by_path.get(f.path)
        if e:
            f.number = e.number
            f.episode = e.title
    say(f"{len(files)} files")
    return files
