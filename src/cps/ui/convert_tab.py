"""Convert video files that are already on disk.

Same job as the Download tab does after a file lands, minus the torrent: point
it at a folder, tick what you want, convert with the selected profile.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core import ffmpeg_setup, settings
from ..core.local_job import LocalJobConfig, find_videos
from .common import (
    confirm_deleting_sources, count_of, human_bytes, human_eta, plain_error,
)


def _files(n: int) -> str:
    return count_of(n, "file")
from .progress_delegate import ProgressDelegate, set_progress
from .style import muted_css
from .worker import LocalJobWorker, retire_on_finish

_CHK, _EP, _NAME, _SIZE, _PROG, _LEFT, _RESULT = range(7)
_HEADERS = ["", "#", "File", "Size", "Progress", "Left", "What happened"]


class ConvertTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.worker: LocalJobWorker | None = None
        self._files: list[Path] = []
        self._selected_rows_at_start: list[int] = []

        self.folder = QLineEdit(str(settings.default_download_dir()))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick)
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(True)
        self.recursive.toggled.connect(lambda _: self._scan())

        self.profile = QComboBox()
        self.out_dir = QLineEdit(str(settings.default_output_dir()))
        out_btn = QPushButton("Browse…")
        out_btn.clicked.connect(lambda: self._pick_into(self.out_dir))

        self.rename = QCheckBox("Rename outputs using the detected episode numbers")
        self.rename.setChecked(True)
        self.delete_source = QCheckBox("Delete each source file after it converts")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        form.addRow("Folder", self._wrap(row))
        form.addRow("Device profile", self.profile)
        orow = QHBoxLayout()
        orow.addWidget(self.out_dir, 1)
        orow.addWidget(out_btn)
        form.addRow("Converted files to", self._wrap(orow))

        self.start_btn = QPushButton("Convert selected")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        self.all_btn = QPushButton("Select all")
        self.all_btn.clicked.connect(lambda: self._check_all(True))
        self.none_btn = QPushButton("Select none")
        self.none_btn.clicked.connect(lambda: self._check_all(False))
        self.rescan_btn = QPushButton("Refresh")
        self.rescan_btn.clicked.connect(self._scan)
        self.open_btn = QPushButton("Open output folder")
        self.open_btn.clicked.connect(self._open_output)
        btns = QHBoxLayout()
        btns.addWidget(self.start_btn)
        btns.addWidget(self.stop_btn)
        btns.addSpacing(24)
        btns.addWidget(self.all_btn)
        btns.addWidget(self.none_btn)
        btns.addStretch(1)
        btns.addWidget(self.open_btn)
        btns.addWidget(self.rescan_btn)

        self.summary = self._build_summary()

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # no zebra striping: rows are separated by a hairline, and a second row
        # colour competes with the stage colour the progress bar is carrying
        self.table.setShowGrid(False)
        self.table.setItemDelegateForColumn(_PROG, ProgressDelegate(self.table))
        self.table.itemChanged.connect(self._on_item_changed)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(_CHK, QHeaderView.Fixed)
        self.table.setColumnWidth(_CHK, 28)
        head.setSectionResizeMode(_EP, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(_NAME, QHeaderView.Stretch)
        head.setSectionResizeMode(_SIZE, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(_PROG, QHeaderView.Fixed)
        self.table.setColumnWidth(_PROG, 190)
        head.setSectionResizeMode(_LEFT, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(_RESULT, QHeaderView.Fixed)
        self.table.setColumnWidth(_RESULT, 280)

        self.empty_hint = QLabel()
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setStyleSheet(muted_css() + " padding: 28px;")

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.recursive)
        lay.addWidget(self.rename)
        lay.addWidget(self.delete_source)
        lay.addLayout(btns)
        lay.addWidget(self.summary)
        lay.addWidget(self.empty_hint, 1)     # takes the slack while the list is empty
        lay.addWidget(self.table, 1)

        self.main.profilesChanged.connect(self._reload_profiles)
        self.main.currentProfileChanged.connect(self._sync_profile)
        self.profile.currentIndexChanged.connect(self._profile_picked)
        self.folder.textChanged.connect(lambda _: self._scan())
        self._reload_profiles()
        self._scan()

    # ------------------------------------------------------------------
    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    def _build_summary(self) -> QFrame:
        box = QFrame()
        box.setFrameShape(QFrame.StyledPanel)
        self.title = QLabel("Nothing selected")
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() + 1.5)
        f.setWeight(QFont.DemiBold)
        self.title.setFont(f)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.count = QLabel("")
        self.bytes = QLabel("")
        self.left = QLabel("")
        for w in (self.count, self.bytes, self.left):
            w.setStyleSheet(muted_css())
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(28)
        grid.addWidget(self.title, 0, 0, 1, 3)
        grid.addWidget(self.bar, 1, 0, 1, 3)
        grid.addWidget(self.count, 2, 0)
        grid.addWidget(self.bytes, 2, 1)
        grid.addWidget(self.left, 2, 2)
        grid.setColumnStretch(2, 1)
        return box

    def _reload_profiles(self) -> None:
        self.profile.blockSignals(True)
        self.profile.clear()
        for p in self.main.profiles:
            self.profile.addItem(p.name, p.id)
        self.profile.blockSignals(False)
        self._sync_profile(self.main.current_profile().id)

    def _sync_profile(self, pid: str) -> None:
        for i in range(self.profile.count()):
            if self.profile.itemData(i) == pid:
                self.profile.blockSignals(True)
                self.profile.setCurrentIndex(i)
                self.profile.blockSignals(False)
                return

    def _profile_picked(self) -> None:
        pid = self.profile.currentData()
        if pid:
            self.main.set_current_profile(pid)

    def _pick(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose a folder of videos",
                                             self.folder.text())
        if d:
            self.folder.setText(d)

    def _pick_into(self, target: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose a folder", target.text())
        if d:
            target.setText(d)

    def _open_output(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        out = Path(self.out_dir.text())
        out.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))

    # -- listing --------------------------------------------------------
    def _scan(self) -> None:
        if self.worker:
            return
        self._files = find_videos(self.folder.text(), self.recursive.isChecked())
        root = Path(self.folder.text())

        from ..core.episode_detect import build_episode_list
        detected = {e.src_rel: e for e in build_episode_list(
            [f.name for f in self._files], self.main.current_profile().episode_regex or None)}

        self.table.blockSignals(True)
        self.table.setRowCount(len(self._files))
        for row, f in enumerate(self._files):
            d = detected.get(f.name)
            chk = QTableWidgetItem()
            chk.setFlags((chk.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
            chk.setCheckState(Qt.Checked)
            self.table.setItem(row, _CHK, chk)

            num = QTableWidgetItem("" if not d or d.number is None else str(d.number))
            num.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, _EP, num)

            try:
                rel = str(f.relative_to(root))
            except ValueError:
                rel = f.name
            name = QTableWidgetItem(rel)
            name.setToolTip(f"{d.title if d else f.stem}\n{f}")
            self.table.setItem(row, _NAME, name)

            size = QTableWidgetItem(human_bytes(f.stat().st_size))
            size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, _SIZE, size)

            prog = QTableWidgetItem()
            set_progress(prog, 0.0, "queued", "Ready")
            self.table.setItem(row, _PROG, prog)
            cell = QTableWidgetItem("")
            cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, _LEFT, cell)
            self.table.setItem(row, _RESULT, QTableWidgetItem(""))
        self.table.blockSignals(False)

        has = bool(self._files)
        self.table.setVisible(has)
        self.empty_hint.setVisible(not has)
        typed = self.folder.text().strip()
        if not typed:
            self.empty_hint.setText(
                "Choose the folder your videos are in — press Browse…")
        elif not Path(typed).is_dir():
            self.empty_hint.setText(
                "That folder isn't there any more.\n"
                "Press Browse… and pick one that is.")
        elif not has:
            self.empty_hint.setText(
                f"There are no videos in “{Path(typed).name}”.\n"
                "Pick a different folder, or tick Include subfolders to look inside it.")
        self._update_selection()

    def _checked_rows(self) -> list[int]:
        return [r for r in range(self.table.rowCount())
                if self.table.item(r, _CHK)
                and self.table.item(r, _CHK).checkState() == Qt.Checked]

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == _CHK and not self.worker:
            picked = item.checkState() == Qt.Checked
            set_progress(self.table.item(item.row(), _PROG), 0.0, "queued",
                         "Ready" if picked else "Not selected")
            self._update_selection()

    def _update_selection(self) -> None:
        rows = self._checked_rows()
        total = sum(self._files[r].stat().st_size for r in rows)
        self.title.setText("Ready to convert" if rows else "Nothing selected")
        # nothing to convert means nothing to press: better than a button that
        # answers with a dialog explaining why it did nothing
        self.start_btn.setEnabled(bool(rows) and self.worker is None)
        self.bar.setValue(0)
        self.count.setText(f"{len(rows)} of {len(self._files)} files")
        self.bytes.setText(human_bytes(total))
        self.left.setText("")

    def _check_all(self, on: bool) -> None:
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            self.table.item(r, _CHK).setCheckState(Qt.Checked if on else Qt.Unchecked)
            set_progress(self.table.item(r, _PROG), 0.0, "queued",
                         "Ready" if on else "Not selected")
        self.table.blockSignals(False)
        self.table.viewport().update()
        self._update_selection()

    # -- running --------------------------------------------------------
    def _start(self) -> None:
        rows = self._checked_rows()
        if not rows:
            QMessageBox.warning(self, "Nothing selected", "Tick at least one file.")
            return
        if not ffmpeg_setup.is_ready():
            from .ffmpeg_dialog import ensure_ffmpeg
            if not ensure_ffmpeg(self):
                return
        if self.delete_source.isChecked() and not confirm_deleting_sources(
                self, len(rows), "video file you picked",
                "of the video files you picked"):
            return

        cfg = LocalJobConfig(
            files=[self._files[r] for r in rows],
            output_root=Path(self.out_dir.text()),
            profile=self.main.current_profile(),
            delete_source=self.delete_source.isChecked(),
            rename_episodes=self.rename.isChecked(),
        )

        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, _CHK)
            item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            set_progress(self.table.item(r, _PROG), 0.0,
                         "queued" if r in rows else "skipped",
                         "Queued" if r in rows else "Not selected")
        self.table.blockSignals(False)
        self.table.viewport().update()
        self._set_running(True)
        self.title.setText(f"Converting {_files(len(rows))}…")
        self.bar.setValue(0)

        self.worker = LocalJobWorker(cfg, parent=self)
        w = self.worker
        w.log.connect(self.main.log)
        w.episodes.connect(self._plan)
        w.episode_update.connect(self._update_episode)
        w.encode_progress.connect(self._enc_progress)
        w.job_progress.connect(self._job_progress)
        w.finished_job.connect(self._finished)
        retire_on_finish(w, self._release)
        w.start()

    def _release(self) -> None:
        self.worker = None

    def _stop(self) -> None:
        if self.worker:
            self.title.setText("Stopping after this file…")
            self.worker.request_stop()
            self.stop_btn.setEnabled(False)

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running and bool(self._checked_rows()))
        self.stop_btn.setEnabled(running)
        for w in (self.folder, self.profile, self.out_dir, self.recursive, self.rename,
                  self.delete_source, self.all_btn, self.none_btn, self.rescan_btn):
            w.setEnabled(not running)

    def _row_for(self, i: int) -> int | None:
        rows = self._selected_rows_at_start
        return rows[i] if 0 <= i < len(rows) else None

    def _plan(self, episodes: list) -> None:
        # the job indexes its own selected list, so map that back to table rows
        self._selected_rows_at_start = self._checked_rows()
        for e in episodes:
            r = self._row_for(e["file_index"])
            if r is not None and e["number"] is not None:
                self.table.item(r, _EP).setText(str(e["number"]))

    def _update_episode(self, e: dict) -> None:
        r = self._row_for(e["file_index"])
        if r is None:
            return
        if e["status"] == "done":
            set_progress(self.table.item(r, _PROG), 1.0, "done", "Done")
            self.table.item(r, _LEFT).setText("")
            self.table.item(r, _RESULT).setText("")
        elif e["status"] == "error":
            set_progress(self.table.item(r, _PROG), 0.0, "error", "Failed")
            self.table.item(r, _LEFT).setText("")
            why = plain_error(e.get("error", ""))
            cell = self.table.item(r, _RESULT)
            cell.setText(why)
            cell.setToolTip(why)          # the raw reason stays in the Log
        self.table.viewport().update()

    def _enc_progress(self, p: dict) -> None:
        r = self._row_for(p["file_index"])
        if r is None:
            return
        set_progress(self.table.item(r, _PROG), p["fraction"], "converting",
                     f"Converting {p['fraction'] * 100:.0f}%")
        self.table.item(r, _LEFT).setText(human_eta(p.get("eta_seconds", 0)))
        self.table.viewport().update()

    def _job_progress(self, p: dict) -> None:
        self.bar.setValue(int(p.get("fraction", 0) * 1000))
        self.count.setText(f"{p['episodes_done']} of {p['episodes_total']} done")
        eta = p.get("eta_seconds", 0)
        self.left.setText(f"about {human_eta(eta)} left" if eta > 0 else "")
        if self.worker is not None:
            self.title.setText(
                f"Converting — {p['episodes_done']} of {p['episodes_total']} done")

    def _finished(self, payload: dict) -> None:
        self._set_running(False)
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, _CHK)
            if item:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        self.table.blockSignals(False)
        done = payload.get("done", 0)
        total = payload.get("total", len(self._selected_rows_at_start))
        failed = max(0, total - done)
        self.left.setText("")
        self.bar.setValue(int(done / total * 1000) if total else 0)

        if payload.get("error") == "stopped":
            # the user pressed Stop; that is not a failure
            self.title.setText(f"Stopped — {_files(done)} converted")
        elif not payload.get("ok"):
            self.title.setText("Could not convert these files")
            QMessageBox.warning(self, "Conversion stopped",
                                plain_error(payload.get("error", "")))
        elif failed:
            self.title.setText(
                f"Converted {done} of {total} — {failed} could not be converted")
            if done == 0:
                body = ("That file could not be converted." if total == 1
                        else f"None of the {total} files could be converted.")
            else:
                body = f"{_files(done)} converted, out of {total}."
            body += ("\n\nThe reason is beside it in the list." if failed == 1
                     else "\n\nThe reason is beside each one in the list.")
            QMessageBox.warning(self, "Some files could not be converted", body)
        else:
            self.title.setText(f"Converted {_files(done)} — ready to send")
            self.bar.setValue(1000)
