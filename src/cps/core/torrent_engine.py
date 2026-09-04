"""libtorrent session wrapper with per-file, one-at-a-time downloading.

The pipeline drives it like this:

    eng = TorrentEngine()
    t = eng.add(magnet_or_torrent, save_path, resume_buf)
    t.wait_metadata(120)
    t.deselect_all()
    for i in order:
        t.select_only(i)
        while not t.file_done(i): ... poll ...
        # convert file i, maybe delete it, then move on
    buf = t.save_resume()

Only the currently-wanted file has non-zero priority, so libtorrent never pulls
the rest of the pack onto disk. A file whose bytes are already deleted stays at
priority 0 and is not re-fetched (we never force a re-check).
"""
from __future__ import annotations

import time
from pathlib import Path

try:
    import libtorrent as lt
except ImportError:  # keeps the module importable for tests / headless dev
    lt = None  # type: ignore

_DL = 4        # normal priority for the active file
_SKIP = 0      # do not download


def _require_lt() -> None:
    if lt is None:
        raise RuntimeError(
            "python 'libtorrent' is not installed. `pip install libtorrent` "
            "(Windows/macOS/Linux wheels are on PyPI for CPython 3.9-3.13)."
        )


class Torrent:
    def __init__(self, handle, engine: "TorrentEngine"):
        self._h = handle
        self._eng = engine

    # -- identity -----------------------------------------------------------
    @property
    def infohash(self) -> str:
        try:
            return str(self._h.info_hashes().get_best())
        except AttributeError:
            return str(self._h.info_hash())

    @property
    def name(self) -> str:
        return self._h.status().name or self.infohash

    # -- metadata ---------------------------------------------------------
    def has_metadata(self) -> bool:
        return self._h.status().has_metadata

    def wait_metadata(self, timeout: float = 120.0) -> None:
        deadline = time.monotonic() + timeout
        while not self.has_metadata():
            if time.monotonic() > deadline:
                raise TimeoutError("timed out fetching torrent metadata (no peers?)")
            self._eng.pump()
            time.sleep(0.5)

    def _ti(self):
        return self._h.torrent_file()

    def files(self) -> list[tuple[str, int]]:
        fs = self._ti().files()
        return [(fs.file_path(i), fs.file_size(i)) for i in range(fs.num_files())]

    def pad_flags(self) -> list[bool]:
        """True for each file index that is a piece-alignment pad file (not real content)."""
        fs = self._ti().files()
        try:
            pad = int(lt.file_storage.flag_pad_file)
            return [bool(fs.file_flags(i) & pad) for i in range(fs.num_files())]
        except Exception:
            out = []
            for i in range(fs.num_files()):
                p = fs.file_path(i).replace("\\", "/").lower()
                out.append("/.pad/" in p or p.startswith(".pad/") or "_____padding_file" in p
                           or "____padding_file" in p)
            return out

    def num_files(self) -> int:
        return self._ti().files().num_files()

    def torrent_file_buf(self) -> bytes:
        """Bencoded .torrent for the current metadata (for resume caching)."""
        ct = lt.create_torrent(self._ti())
        return lt.bencode(ct.generate())

    # -- selection ------------------------------------------------------
    def deselect_all(self) -> None:
        self._h.prioritize_files([_SKIP] * self.num_files())

    def select_only(self, index: int, priority: int = _DL) -> None:
        prios = [_SKIP] * self.num_files()
        prios[index] = priority
        self._h.prioritize_files(prios)
        try:
            self._h.set_flags(lt.torrent_flags.sequential_download)
        except Exception:
            pass
        self.resume()

    def set_priority(self, index: int, priority: int) -> None:
        self._h.file_priority(index, priority)

    def connect_peer(self, host: str, port: int) -> None:
        """Add a peer by hand — useful on a LAN with no tracker/DHT."""
        try:
            self._h.connect_peer((host, int(port)))
        except Exception:
            pass

    # -- progress -----------------------------------------------------
    def file_bytes(self, index: int) -> int:
        try:
            return self._h.file_progress()[index]
        except (IndexError, RuntimeError):
            return 0

    def file_fraction(self, index: int) -> float:
        _, size = self.files()[index]
        if size <= 0:
            return 1.0
        return min(1.0, self.file_bytes(index) / size)

    def file_done(self, index: int) -> bool:
        _, size = self.files()[index]
        return self.file_bytes(index) >= size > 0

    def status(self) -> dict:
        s = self._h.status()
        return {
            "download_rate": s.download_rate,      # bytes/s
            "upload_rate": s.upload_rate,
            "num_peers": s.num_peers,
            "num_seeds": s.num_seeds,
            "state": str(s.state),
            "progress": s.progress,
        }

    # -- control ------------------------------------------------------
    def pause(self) -> None:
        self._h.pause()

    def resume(self) -> None:
        self._h.resume()

    def save_resume(self, timeout: float = 10.0) -> bytes | None:
        if not self._h.is_valid() or not self.has_metadata():
            return None
        self._h.save_resume_data()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for a in self._eng.pump():
                if isinstance(a, lt.save_resume_data_alert):
                    return lt.write_resume_data_buf(a.params)
                if isinstance(a, lt.save_resume_data_failed_alert):
                    return None
            time.sleep(0.2)
        return None

    def remove(self, delete_files: bool = False) -> None:
        flag = lt.session.delete_files if delete_files else 0
        self._eng.session.remove_torrent(self._h, flag)


class TorrentEngine:
    def __init__(self, port: int = 6881):
        _require_lt()
        self.session = lt.session({
            "listen_interfaces": f"0.0.0.0:{port},[::]:{port}",
            "alert_mask": lt.alert.category_t.status_notification
            | lt.alert.category_t.error_notification
            | lt.alert.category_t.storage_notification,
        })

    def pump(self) -> list:
        return self.session.pop_alerts()

    def add(self, source: str, save_path: str | Path, resume_buf: bytes | None = None,
            ti_path: str | Path | None = None, upload_mode: bool = False) -> Torrent:
        save_path = str(save_path)
        Path(save_path).mkdir(parents=True, exist_ok=True)

        if resume_buf:
            atp = lt.read_resume_data(resume_buf)
        elif source.startswith("magnet:"):
            atp = lt.parse_magnet_uri(source)
        else:
            atp = lt.add_torrent_params()
            atp.ti = lt.torrent_info(source)

        # resume data does not always carry the torrent info; re-attach it so a
        # resumed job has metadata immediately instead of re-fetching from peers
        if getattr(atp, "ti", None) is None:
            cand = ti_path or (source if not source.startswith("magnet:") else None)
            if cand and Path(cand).is_file():
                atp.ti = lt.torrent_info(str(cand))

        atp.save_path = save_path
        # start every file de-selected; the pipeline turns one on at a time
        if atp.ti is not None:
            atp.file_priorities = [_SKIP] * atp.ti.files().num_files()
        if upload_mode:
            # fetch metadata / connect to peers but never write file data to disk
            atp.flags |= lt.torrent_flags.upload_mode
        handle = self.session.add_torrent(atp)
        return Torrent(handle, self)

    def shutdown(self) -> None:
        try:
            self.session.pause()
        except Exception:
            pass
