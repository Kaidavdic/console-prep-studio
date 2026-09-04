"""QThread wrappers that turn pipeline / sender callbacks into Qt signals.

Lifetime rule, learned the hard way: a worker must never be dropped from inside a
slot connected to a signal the worker emits from its own `run()`. Doing that frees
the C++ QThread while it is still running and Qt calls std::terminate — the whole
app vanishes with no traceback. Always retire a worker via `retire_on_finish()`,
which waits for QThread.finished (emitted only after run() has returned).
"""
from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QThread, Signal

from ..core.metadata import fetch_file_list
from ..core.pipeline import JobConfig, Pipeline
from ..core.profiles import Profile
from ..core.sender import send_batch
from ..core.torrent_engine import TorrentEngine


def retire_on_finish(worker: QThread, clear: Callable[[], None]) -> None:
    """Release `worker` only once its run() has actually returned."""
    def _done() -> None:
        clear()
        worker.deleteLater()
    worker.finished.connect(_done)


class _Worker(QThread):
    """Common base: never let an exception escape run()."""

    def run(self) -> None:
        try:
            self.work()
        except Exception as e:  # noqa: BLE001 - a raise here would kill the process
            self.on_crash(e)

    def work(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def on_crash(self, exc: Exception) -> None:  # pragma: no cover - overridden
        pass


class MetadataWorker(_Worker):
    status = Signal(str)
    files_ready = Signal(list)          # list[TorrentFile]
    failed = Signal(str)

    def __init__(self, source: str, port: int = 6881, regex: str = "", parent=None):
        super().__init__(parent)
        self.source = source
        self.port = port
        self.regex = regex or None

    def work(self) -> None:
        files = fetch_file_list(self.source, timeout=120, port=self.port,
                                regex=self.regex, on_status=self.status.emit)
        self.files_ready.emit(files)

    def on_crash(self, exc: Exception) -> None:
        self.failed.emit(str(exc))


class PipelineWorker(_Worker):
    log = Signal(str)
    phase = Signal(str)
    episodes = Signal(list)
    episode_update = Signal(dict)
    download_progress = Signal(dict)
    encode_progress = Signal(dict)
    job_progress = Signal(dict)
    finished_job = Signal(dict)

    def __init__(self, cfg: JobConfig, port: int = 6881, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.port = port
        self._stop = threading.Event()
        self._engine: TorrentEngine | None = None

    def request_stop(self) -> None:
        self._stop.set()

    def _emit(self, kind: str, payload: dict) -> None:
        sig = {
            "log": self.log,
            "phase": self.phase,
            "episodes": self.episodes,
            "episode_update": self.episode_update,
            "download_progress": self.download_progress,
            "encode_progress": self.encode_progress,
            "job_progress": self.job_progress,
            "finished": self.finished_job,
        }.get(kind)
        if sig is None:
            return
        if kind == "log":
            sig.emit(payload["msg"])
        elif kind == "phase":
            sig.emit(payload.get("phase", ""))
        elif kind == "episodes":
            sig.emit(payload["episodes"])
        else:
            sig.emit(payload)

    def work(self) -> None:
        try:
            self._engine = TorrentEngine(port=self.port)
        except Exception as e:  # noqa: BLE001
            self.log.emit(f"cannot start torrent engine: {e}")
            self.finished_job.emit({"ok": False, "error": str(e)})
            return
        try:
            Pipeline(self.cfg, self._engine, self._emit, self._stop.is_set).run()
        finally:
            engine, self._engine = self._engine, None
            if engine is not None:
                engine.shutdown()

    def on_crash(self, exc: Exception) -> None:
        self.log.emit(f"worker crashed: {exc}")
        self.finished_job.emit({"ok": False, "error": str(exc)})


class SendWorker(_Worker):
    event = Signal(str, dict)
    done = Signal(list)

    def __init__(self, profile: Profile, folder: str, files=None, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.folder = folder
        self.files = files            # list[Path] | None -> None means "whole folder"
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def work(self) -> None:
        items = send_batch(self.profile, self.folder,
                           lambda k, p: self.event.emit(k, p), self._stop.is_set,
                           files=self.files)
        self.done.emit([vars(i) for i in items])

    def on_crash(self, exc: Exception) -> None:
        self.event.emit("log", {"msg": f"send failed: {exc}"})
        self.done.emit([])
