"""Main window: five tabs over the shared profile list + one torrent engine port."""
from __future__ import annotations

import sys

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QTabWidget,
)

from . import APP_NAME, __version__
from .core import ffmpeg_setup, settings
from .core.profiles import Profile, load_profiles, save_profiles
from .ui import crashlog
from .ui.compression_tab import CompressionTab
from .ui.download_tab import DownloadTab
from .ui.ffmpeg_dialog import ensure_ffmpeg
from .ui.log_tab import LogTab
from .ui.profiles_tab import ProfilesTab
from .ui.send_tab import SendTab
from .ui.style import app_stylesheet


class MainWindow(QMainWindow):
    profilesChanged = Signal()
    currentProfileChanged = Signal(str)   # profile id

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(940, 680)

        self.profiles: list[Profile] = load_profiles()
        self._current_id: str = self.profiles[0].id if self.profiles else ""

        self.log_tab = LogTab(self)
        self.profiles_tab = ProfilesTab(self)
        self.compression_tab = CompressionTab(self)
        self.download_tab = DownloadTab(self)
        self.send_tab = SendTab(self)

        tabs = QTabWidget()
        tabs.addTab(self.download_tab, "Download")
        tabs.addTab(self.compression_tab, "Compression")
        tabs.addTab(self.profiles_tab, "Console Profiles")
        tabs.addTab(self.send_tab, "Send")
        tabs.addTab(self.log_tab, "Log")
        self.setCentralWidget(tabs)

        self.statusBar().showMessage(f"data: {settings.data_dir()}")

    # -- shared profile state --------------------------------------
    def current_profile(self) -> Profile:
        for p in self.profiles:
            if p.id == self._current_id:
                return p
        return self.profiles[0]

    def set_current_profile(self, pid: str) -> None:
        if pid and pid != self._current_id:
            self._current_id = pid
            self.currentProfileChanged.emit(pid)

    def refresh_profiles(self, select_id: str | None = None) -> None:
        self.profiles = load_profiles()
        if select_id:
            self._current_id = select_id
        elif not any(p.id == self._current_id for p in self.profiles):
            self._current_id = self.profiles[0].id
        self.profilesChanged.emit()
        self.currentProfileChanged.emit(self._current_id)

    def persist_profiles(self) -> None:
        save_profiles(self.profiles)
        self.profilesChanged.emit()

    def log(self, msg: str) -> None:
        self.log_tab.append(msg)

    def closeEvent(self, event) -> None:
        """Ask running workers to stop and wait, so nothing is torn down mid-run."""
        workers = [self.download_tab.worker, self.download_tab.meta_worker,
                   self.download_tab.send_worker, self.send_tab.worker]
        live = [w for w in workers if w is not None and w.isRunning()]
        for w in live:
            if hasattr(w, "request_stop"):
                w.request_stop()
        for w in live:
            w.wait(8000)
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    crashlog.install()
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(app_stylesheet())

    win = MainWindow()
    win.show()

    if not ffmpeg_setup.is_ready():
        if not ensure_ffmpeg(win):
            QMessageBox.warning(
                win, "ffmpeg needed",
                "Conversions won't run until ffmpeg is available. "
                "Use the Compression tab's 'Locate ffmpeg' button later.",
            )

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
