from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog, QMessageBox, QProgressDialog, QWidget,
)

from ..core import ffmpeg_setup


class _DownloadThread(QThread):
    progress = Signal(int, int)
    done = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            ffmpeg_setup.download(self._report)
            self.done.emit(True, "")
        except _Cancelled:
            self.done.emit(False, "")
        except Exception as e:  # noqa: BLE001
            self.done.emit(False, str(e))

    def _report(self, got: int, total: int) -> None:
        if self._stop.is_set():
            raise _Cancelled
        self.progress.emit(got, total)


class _Cancelled(Exception):
    """Raised inside the download callback so Cancel actually stops the work."""


def ensure_ffmpeg(parent: QWidget) -> bool:
    """Prompt to download or locate ffmpeg. Returns True if ffmpeg is ready after."""
    if ffmpeg_setup.is_ready():
        return True

    # A three-way choice, so the buttons say what they do. Yes/No/Cancel made
    # the reader work out that "No" meant "let me find it myself".
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("One more thing is needed")
    box.setText("Console Prep Studio needs a small video tool before it can "
                "convert anything.")
    box.setInformativeText(
        "It is a free download of about 30 MB and it goes in this app's own "
        "folder — nothing else on your computer changes.")
    get_it = box.addButton("Download it for me", QMessageBox.AcceptRole)
    have_it = box.addButton("I already have it", QMessageBox.ActionRole)
    not_now = box.addButton("Not now", QMessageBox.RejectRole)
    box.setDefaultButton(get_it)
    box.setEscapeButton(not_now)
    box.exec()

    if box.clickedButton() is not_now:
        return False
    if box.clickedButton() is have_it:
        d = QFileDialog.getExistingDirectory(
            parent, "Find the folder that contains ffmpeg")
        if not d:
            return False
        try:
            ffmpeg_setup.set_manual_dir(d)
            return ffmpeg_setup.is_ready()
        except ffmpeg_setup.FfmpegMissing:
            QMessageBox.warning(
                parent, "Not in that folder",
                "That folder doesn't have the video tool in it. Try the folder "
                "you unzipped it into — it usually has a “bin” folder inside.")
            return False

    dlg = QProgressDialog("Downloading the video tool…", "Cancel", 0, 100, parent)
    dlg.setWindowTitle("Getting set up")
    dlg.setMinimumDuration(0)
    th = _DownloadThread(parent)
    result = {"ok": False}

    def on_progress(got: int, total: int) -> None:
        dlg.setMaximum(total or 0)
        dlg.setValue(got)

    def on_done(ok: bool, err: str) -> None:
        result["ok"] = ok
        dlg.reset()
        if not ok and err:
            QMessageBox.warning(
                parent, "The download did not finish",
                "The video tool could not be downloaded. Check your internet "
                "connection and try again from Settings.")

    th.progress.connect(on_progress)
    th.done.connect(on_done)
    dlg.canceled.connect(th.request_stop)      # Cancel really does stop it
    th.start()
    dlg.exec()
    th.wait(5000)
    return result["ok"] and ffmpeg_setup.is_ready()
