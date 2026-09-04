"""Main window.

Three destinations instead of six tabs. Work happens in one place — the source
of the work is a switch inside it, not a separate tab — and the things you
configure once live together under Settings.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QMessageBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

from . import APP_NAME, __version__
from .core import ffmpeg_setup, settings
from .core.profiles import Profile, load_profiles, save_profiles
from .ui import crashlog
from .ui.compression_tab import CompressionTab
from .ui.convert_tab import ConvertTab
from .ui.download_tab import DownloadTab
from .ui.ffmpeg_dialog import ensure_ffmpeg
from .ui.log_tab import LogTab
from .ui.profiles_tab import ProfilesTab
from .ui.send_tab import SendTab
from .ui.theme import C, S, stylesheet
from .ui.widgets import NavBar, Rule, Segmented


def _page(switch: Segmented, stack: QStackedWidget) -> QWidget:
    """A destination that holds a few related screens behind one switch."""
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    row = QHBoxLayout()
    row.setContentsMargins(S.xl, S.md, S.xl, 0)
    row.addWidget(switch)
    lay.addLayout(row)
    lay.addWidget(stack, 1)
    switch.changed.connect(stack.setCurrentIndex)
    return page


class MainWindow(QMainWindow):
    profilesChanged = Signal()
    currentProfileChanged = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1060, 780)

        self.profiles: list[Profile] = load_profiles()
        self._current_id: str = self.profiles[0].id if self.profiles else ""

        self.log_tab = LogTab(self)
        self.profiles_tab = ProfilesTab(self)
        self.compression_tab = CompressionTab(self)
        self.download_tab = DownloadTab(self)
        self.convert_tab = ConvertTab(self)
        self.send_tab = SendTab(self)

        # --- Jobs: three ways work arrives, one place it happens ---
        jobs_stack = QStackedWidget()
        for w in (self.download_tab, self.convert_tab, self.send_tab):
            jobs_stack.addWidget(w)
        jobs = _page(Segmented(["From a torrent", "From a folder", "Send to device"]),
                     jobs_stack)

        # --- Settings: the things you set once ---
        settings_stack = QStackedWidget()
        for w in (self.compression_tab, self.profiles_tab):
            settings_stack.addWidget(w)
        setts = _page(Segmented(["Video and audio", "Devices"]), settings_stack)

        self.pages = QStackedWidget()
        for w in (jobs, setts, self.log_tab):
            self.pages.addWidget(w)

        self.nav = NavBar(["Jobs", "Settings", "Log"])
        self.nav.changed.connect(self.pages.setCurrentIndex)

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.nav)
        lay.addWidget(Rule())
        lay.addWidget(self.pages, 1)
        self.setCentralWidget(root)

        self.statusBar().showMessage(str(settings.data_dir()))

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
        workers = [self.download_tab.worker, self.download_tab.meta_worker,
                   self.download_tab.send_worker, self.send_tab.worker,
                   self.convert_tab.worker]
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
    app.setStyle("Fusion")            # a predictable base for the sheet to sit on
    app.setStyleSheet(stylesheet())

    win = MainWindow()
    win.show()

    if not ffmpeg_setup.is_ready():
        if not ensure_ffmpeg(win):
            QMessageBox.warning(
                win, "ffmpeg needed",
                "Conversions won't run until ffmpeg is available. "
                "Settings has a button to find or download it.")

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
