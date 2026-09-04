from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog, QMessageBox, QProgressDialog, QWidget,
)

from ..core import ffmpeg_setup


class _DownloadThread(QThread):
    progress = Signal(int, int)
    done = Signal(bool, str)

    def run(self) -> None:
        try:
            ffmpeg_setup.download(lambda g, t: self.progress.emit(g, t))
            self.done.emit(True, "")
        except Exception as e:  # noqa: BLE001
            self.done.emit(False, str(e))


def ensure_ffmpeg(parent: QWidget) -> bool:
    """Prompt to download or locate ffmpeg. Returns True if ffmpeg is ready after."""
    if ffmpeg_setup.is_ready():
        return True

    choice = QMessageBox.question(
        parent, "ffmpeg is needed to convert video",
        "ffmpeg and ffprobe were not found on this computer.\n\n"
        "Download a static build now? It goes in this app's own folder and takes "
        "about 30 MB.\n\n"
        "Choose No to point at a copy you already have "
        f"({ffmpeg_setup.install_hint()}).",
        QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
    )
    if choice == QMessageBox.Cancel:
        return False
    if choice == QMessageBox.No:
        d = QFileDialog.getExistingDirectory(parent, "Folder containing ffmpeg.exe / ffprobe.exe")
        if not d:
            return False
        try:
            ffmpeg_setup.set_manual_dir(d)
            return ffmpeg_setup.is_ready()
        except ffmpeg_setup.FfmpegMissing as e:
            QMessageBox.warning(parent, "Not found", str(e))
            return False

    dlg = QProgressDialog("Downloading ffmpeg...", "Cancel", 0, 100, parent)
    dlg.setWindowTitle("ffmpeg")
    dlg.setMinimumDuration(0)
    th = _DownloadThread(parent)
    result = {"ok": False}

    def on_progress(got: int, total: int) -> None:
        dlg.setMaximum(total or 0)
        dlg.setValue(got)

    def on_done(ok: bool, err: str) -> None:
        result["ok"] = ok
        dlg.close()
        if not ok:
            QMessageBox.warning(parent, "Download failed", err)

    th.progress.connect(on_progress)
    th.done.connect(on_done)
    th.start()
    dlg.exec()
    th.wait(1000)
    return result["ok"] and ffmpeg_setup.is_ready()
