from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core import ffmpeg_setup, settings
from ..core.pipeline import JobConfig
from .common import human_bytes, human_eta, human_rate
from .progress_delegate import ProgressDelegate, set_progress
from .style import muted_css, stage_of
from .worker import MetadataWorker, PipelineWorker, SendWorker, retire_on_finish

_CHK, _EP, _NAME, _SIZE, _PROG, _SPEED, _LEFT = range(7)
_HEADERS = ["", "#", "Name", "Size", "Progress", "Speed", "Left"]


class DownloadTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.worker: PipelineWorker | None = None
        self.meta_worker: MetadataWorker | None = None
        self.send_worker: SendWorker | None = None
        self._files: list = []                  # one TorrentFile per row (pads hidden)
        self._row_by_fidx: dict[int, int] = {}  # torrent file index -> table row

        # ---- source + settings form ----
        self.profile = QComboBox()
        self.source = QLineEdit()
        self.source.setPlaceholderText("magnet:?xt=urn:btih:…   or a path to a .torrent file")
        self.source.textChanged.connect(self._source_changed)
        self.source.returnPressed.connect(self._load)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_torrent)
        self.load_btn = QPushButton("Load files")
        self.load_btn.setDefault(True)
        self.load_btn.clicked.connect(self._load)

        self.save_dir = QLineEdit(str(settings.default_download_dir()))
        save_btn = QPushButton("Browse…")
        save_btn.clicked.connect(lambda: self._pick_dir(self.save_dir))
        self.out_dir = QLineEdit(str(settings.default_output_dir()))
        out_btn = QPushButton("Browse…")
        out_btn.clicked.connect(lambda: self._pick_dir(self.out_dir))

        self.delete_source = QCheckBox("Delete each source file once it has been converted")
        self.delete_source.setChecked(True)
        self.delete_source.toggled.connect(self._delete_hint)
        self.delete_note = QLabel()
        self.delete_note.setWordWrap(True)
        self.delete_note.setStyleSheet(muted_css())

        self.limit = QSpinBox()
        self.limit.setRange(0, 9999)
        self.limit.setSpecialValueText("no limit")
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(6881)
        self.autosend = QCheckBox("Send everything to the device when the job finishes")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row = QHBoxLayout()
        row.addWidget(self.source, 1)
        row.addWidget(browse)
        row.addWidget(self.load_btn)
        form.addRow("Torrent", self._wrap(row))
        form.addRow("Device profile", self.profile)
        form.addRow("Download to", self._path_row(self.save_dir, save_btn))
        form.addRow("Converted files to", self._path_row(self.out_dir, out_btn))
        opts = QHBoxLayout()
        opts.addWidget(QLabel("Stop after"))
        opts.addWidget(self.limit)
        opts.addWidget(QLabel("episodes"))
        opts.addSpacing(24)
        opts.addWidget(QLabel("BitTorrent port"))
        opts.addWidget(self.port)
        opts.addStretch(1)
        form.addRow("Limits", self._wrap(opts))

        # ---- actions ----
        self.start_btn = QPushButton("Start")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        self.all_btn = QPushButton("Select all")
        self.all_btn.clicked.connect(lambda: self._check_all(True))
        self.none_btn = QPushButton("Select none")
        self.none_btn.clicked.connect(lambda: self._check_all(False))
        self.vids_btn = QPushButton("Videos only")
        self.vids_btn.clicked.connect(self._check_videos)
        self.open_btn = QPushButton("Open output folder")
        self.open_btn.clicked.connect(self._open_output)
        for b in (self.all_btn, self.none_btn, self.vids_btn):
            b.setEnabled(False)
        actions = QHBoxLayout()
        actions.addWidget(self.start_btn)
        actions.addWidget(self.stop_btn)
        actions.addSpacing(24)
        actions.addWidget(self.all_btn)
        actions.addWidget(self.none_btn)
        actions.addWidget(self.vids_btn)
        actions.addStretch(1)
        actions.addWidget(self.open_btn)

        # ---- job summary strip ----
        self.summary = self._build_summary()

        # ---- file table ----
        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
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
        head.setSectionResizeMode(_SPEED, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(_LEFT, QHeaderView.ResizeToContents)

        self.empty_hint = QLabel(
            "Paste a magnet link or pick a .torrent file, then choose Load files "
            "to see what's inside it.")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setStyleSheet(muted_css() + " padding: 28px;")

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.delete_source)
        lay.addWidget(self.delete_note)
        lay.addWidget(self.autosend)
        lay.addLayout(actions)
        lay.addWidget(self.summary)
        lay.addWidget(self.empty_hint)
        lay.addWidget(self.table, 1)

        self.main.profilesChanged.connect(self._reload_profiles)
        self.main.currentProfileChanged.connect(self._sync_profile_combo)
        self.profile.currentIndexChanged.connect(self._profile_picked)
        self._reload_profiles()
        self._delete_hint(True)
        self._show_table(False)

    # ------------------------------------------------------------------
    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    def _path_row(self, edit: QLineEdit, btn: QPushButton) -> QWidget:
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(btn)
        return self._wrap(row)

    def _build_summary(self) -> QFrame:
        box = QFrame()
        box.setFrameShape(QFrame.StyledPanel)
        self.job_title = QLabel("No job running")
        f = self.job_title.font()
        f.setPointSizeF(f.pointSizeF() + 1.5)
        f.setWeight(QFont.DemiBold)
        self.job_title.setFont(f)

        self.job_bar = QProgressBar()
        self.job_bar.setRange(0, 1000)
        self.job_bar.setValue(0)
        self.job_bar.setTextVisible(False)
        self.job_bar.setFixedHeight(8)

        self.job_count = QLabel("")
        self.job_bytes = QLabel("")
        self.job_rate = QLabel("")
        self.job_left = QLabel("")
        for w in (self.job_count, self.job_bytes, self.job_rate, self.job_left):
            w.setStyleSheet(muted_css())

        grid = QGridLayout(box)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(28)
        grid.addWidget(self.job_title, 0, 0, 1, 4)
        grid.addWidget(self.job_bar, 1, 0, 1, 4)
        grid.addWidget(self.job_count, 2, 0)
        grid.addWidget(self.job_bytes, 2, 1)
        grid.addWidget(self.job_rate, 2, 2)
        grid.addWidget(self.job_left, 2, 3)
        grid.setColumnStretch(3, 1)
        box.setVisible(False)
        return box

    def _show_table(self, on: bool) -> None:
        self.table.setVisible(on)
        self.empty_hint.setVisible(not on)

    # ------------------------------------------------------------------
    def _reload_profiles(self) -> None:
        self.profile.blockSignals(True)
        self.profile.clear()
        for p in self.main.profiles:
            self.profile.addItem(p.name, p.id)
        self.profile.blockSignals(False)
        self._sync_profile_combo(self.main.current_profile().id)

    def _sync_profile_combo(self, pid: str) -> None:
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

    def _delete_hint(self, on: bool) -> None:
        self.delete_note.setText(
            "Only one source file sits on disk at a time. The torrent finishes at a "
            "zero ratio, because there is nothing left to seed." if on else
            "Sources are kept, so you can keep seeding. You need room for everything "
            "you selected until you delete them yourself.")

    def _browse_torrent(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Choose a torrent file", "",
                                           "Torrent files (*.torrent)")
        if f:
            self.source.setText(f)

    def _pick_dir(self, target: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose a folder", target.text())
        if d:
            target.setText(d)

    def _open_output(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        Path(self.out_dir.text()).mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.out_dir.text()))

    def _source_changed(self) -> None:
        if self.worker:
            return
        self._files = []
        self._row_by_fidx = {}
        self.table.setRowCount(0)
        self._show_table(False)
        self.start_btn.setEnabled(False)
        for b in (self.all_btn, self.none_btn, self.vids_btn):
            b.setEnabled(False)
        self.summary.setVisible(False)

    # -- reading the torrent -------------------------------------------
    def _load(self) -> None:
        src = self.source.text().strip()
        if not src:
            QMessageBox.warning(self, "Nothing to load",
                                "Paste a magnet link, or choose a .torrent file.")
            return
        if not src.startswith("magnet:") and not Path(src).is_file():
            QMessageBox.warning(self, "File not found",
                                f"There is no file at:\n{src}")
            return
        self.load_btn.setEnabled(False)
        self.empty_hint.setText("Reading the torrent…")
        self._show_table(False)
        self.meta_worker = MetadataWorker(src, port=self.port.value(),
                                          regex=self.main.current_profile().episode_regex,
                                          parent=self)
        self.meta_worker.status.connect(
            lambda s: self.empty_hint.setText(f"Reading the torrent — {s}"))
        self.meta_worker.files_ready.connect(self._show_files)
        self.meta_worker.failed.connect(self._load_failed)
        retire_on_finish(self.meta_worker, lambda: setattr(self, "meta_worker", None))
        self.meta_worker.start()

    def _load_failed(self, err: str) -> None:
        self.load_btn.setEnabled(True)
        self.empty_hint.setText(
            "Paste a magnet link or pick a .torrent file, then choose Load files "
            "to see what's inside it.")
        self._show_table(False)
        QMessageBox.warning(
            self, "Could not read the torrent",
            f"{err}\n\nA magnet link needs peers before it can hand over its file "
            "list. Try again in a moment, or use a .torrent file instead.")

    def _show_files(self, files: list) -> None:
        self.load_btn.setEnabled(True)
        self._files = files
        self._row_by_fidx = {f.index: row for row, f in enumerate(files)}

        self.table.blockSignals(True)
        self.table.setRowCount(len(files))
        for row, f in enumerate(files):
            chk = QTableWidgetItem()
            chk.setFlags((chk.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
            chk.setCheckState(Qt.Checked if f.is_video else Qt.Unchecked)
            self.table.setItem(row, _CHK, chk)

            num = QTableWidgetItem("" if f.number is None else str(f.number))
            num.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, _EP, num)

            name = QTableWidgetItem(Path(f.path).name)
            name.setToolTip(f.path)
            if not f.is_video:
                name.setForeground(QBrush(QColor(140, 140, 140)))
            self.table.setItem(row, _NAME, name)

            size = QTableWidgetItem(human_bytes(f.size))
            size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, _SIZE, size)

            prog = QTableWidgetItem()
            set_progress(prog, 0.0, "queued", "Not selected" if not f.is_video else "Ready")
            self.table.setItem(row, _PROG, prog)

            for col in (_SPEED, _LEFT):
                cell = QTableWidgetItem("")
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, col, cell)
        self.table.blockSignals(False)

        self._show_table(True)
        for b in (self.all_btn, self.none_btn, self.vids_btn):
            b.setEnabled(True)
        self.start_btn.setEnabled(True)
        self._update_selection_summary()

    # -- selection ------------------------------------------------------
    def _checked_rows(self) -> list[int]:
        return [r for r in range(self.table.rowCount())
                if self.table.item(r, _CHK)
                and self.table.item(r, _CHK).checkState() == Qt.Checked]

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == _CHK and not self.worker:
            row = item.row()
            picked = item.checkState() == Qt.Checked
            cell = self.table.item(row, _PROG)
            if cell:
                set_progress(cell, 0.0, "queued", "Ready" if picked else "Not selected")
            self._update_selection_summary()

    def _update_selection_summary(self) -> None:
        rows = self._checked_rows()
        total = sum(self._files[r].size for r in rows) if self._files else 0
        videos = sum(1 for r in rows if self._files[r].is_video)
        self.summary.setVisible(True)
        self.job_title.setText(self._torrent_name())
        self.job_bar.setValue(0)
        self.job_count.setText(f"{len(rows)} selected, {videos} video")
        self.job_bytes.setText(f"{human_bytes(total)} to download")
        self.job_rate.setText("")
        self.job_left.setText("")

    def _torrent_name(self) -> str:
        if not self._files:
            return "No job running"
        first = Path(self._files[0].path)
        return first.parts[0] if len(first.parts) > 1 else first.stem

    def _check_all(self, on: bool) -> None:
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            self.table.item(r, _CHK).setCheckState(Qt.Checked if on else Qt.Unchecked)
            set_progress(self.table.item(r, _PROG), 0.0, "queued",
                         "Ready" if on else "Not selected")
        self.table.blockSignals(False)
        self.table.viewport().update()
        self._update_selection_summary()

    def _check_videos(self) -> None:
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            keep = self._files[r].is_video
            self.table.item(r, _CHK).setCheckState(Qt.Checked if keep else Qt.Unchecked)
            set_progress(self.table.item(r, _PROG), 0.0, "queued",
                         "Ready" if keep else "Not selected")
        self.table.blockSignals(False)
        self.table.viewport().update()
        self._update_selection_summary()

    # -- running --------------------------------------------------------
    def _start(self) -> None:
        src = self.source.text().strip()
        if not self._files:
            QMessageBox.warning(self, "Load the torrent first",
                                "Choose Load files, then tick what you want to keep.")
            return
        rows = self._checked_rows()
        if not rows:
            QMessageBox.warning(self, "Nothing selected",
                                "Tick at least one file to process.")
            return
        if not ffmpeg_setup.is_ready():
            from .ffmpeg_dialog import ensure_ffmpeg
            if not ensure_ffmpeg(self):
                return

        cfg = JobConfig(
            source=src,
            save_path=Path(self.save_dir.text()),
            output_root=Path(self.out_dir.text()),
            profile=self.main.current_profile(),
            delete_source=self.delete_source.isChecked(),
            episode_limit=(self.limit.value() or None),
            selected_files=[self._files[r].path for r in rows],
        )

        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, _CHK)
            item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            picked = r in rows
            set_progress(self.table.item(r, _PROG), 0.0,
                         "queued" if picked else "skipped",
                         "Queued" if picked else "Not selected")
        self.table.blockSignals(False)
        self.table.viewport().update()

        self._set_running(True)
        self.worker = PipelineWorker(cfg, port=self.port.value(), parent=self)
        w = self.worker
        w.log.connect(self.main.log)
        w.episodes.connect(self._plan)
        w.episode_update.connect(self._update_episode)
        w.download_progress.connect(self._dl_progress)
        w.encode_progress.connect(self._enc_progress)
        w.job_progress.connect(self._job_progress)
        w.finished_job.connect(self._finished)
        # release the thread only after run() has returned - never inside a slot
        retire_on_finish(w, self._release_worker)
        w.start()

    def _release_worker(self) -> None:
        self.worker = None

    def _stop(self) -> None:
        if self.worker:
            self.job_title.setText("Stopping after the current step…")
            self.worker.request_stop()
            self.stop_btn.setEnabled(False)

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        for w in (self.source, self.profile, self.save_dir, self.out_dir, self.load_btn,
                  self.delete_source, self.limit, self.port,
                  self.all_btn, self.none_btn, self.vids_btn):
            w.setEnabled(not running)

    def _row_for(self, file_index: int) -> int | None:
        return self._row_by_fidx.get(file_index)

    def _set_row(self, row: int, fraction: float, stage: str, label: str,
                 speed: str = "", left: str = "") -> None:
        cell = self.table.item(row, _PROG)
        if cell is not None:
            set_progress(cell, fraction, stage, label)
        self.table.item(row, _SPEED).setText(speed)
        self.table.item(row, _LEFT).setText(left)
        self.table.viewport().update()

    def _plan(self, episodes: list) -> None:
        planned = set()
        for e in episodes:
            r = self._row_for(e["file_index"])
            if r is None:
                continue
            planned.add(r)
            if e["number"] is not None:
                self.table.item(r, _EP).setText(str(e["number"]))
            self.table.item(r, _NAME).setToolTip(
                f"{e['title']}\n{self._files[r].path}")
        for r in self._checked_rows():
            if r not in planned:
                self._set_row(r, 0.0, "skipped", "No episode found")

    def _update_episode(self, e: dict) -> None:
        row = self._row_for(e["file_index"])
        if row is None:
            return
        status = e["status"]
        if status == "done":
            self._set_row(row, 1.0, "done", "Done")
        elif status == "error":
            self._set_row(row, 0.0, "error", "Failed")
            self.table.item(row, _NAME).setToolTip(e.get("error", ""))
            self.main.log(f"{e['title']}: {e.get('error', '')}")
        elif status == "downloading":
            self._set_row(row, 0.0, "downloading", "Downloading")

    def _dl_progress(self, p: dict) -> None:
        row = self._row_for(p["file_index"])
        if row is None:
            return
        pct = p["fraction"] * 100
        if p["fraction"] >= 1.0:
            self._set_row(row, 1.0, "downloading", "Downloaded")
        else:
            self._set_row(row, p["fraction"], "downloading", f"Downloading {pct:.0f}%",
                          human_rate(p.get("rate", 0)),
                          human_eta(p.get("eta_seconds", 0)))

    def _enc_progress(self, p: dict) -> None:
        row = self._row_for(p["file_index"])
        if row is None:
            return
        mode = "burned-in subs" if p.get("mode") == "burn-in" else "soft subs"
        speed = p.get("speed_x") or 0
        self._set_row(row, p["fraction"], "converting",
                      f"Converting {p['fraction'] * 100:.0f}%",
                      f"{speed:.1f}x" if speed else "",
                      human_eta(p.get("eta_seconds", 0)))
        self.table.item(row, _NAME).setToolTip(f"Converting to {mode}")

    def _job_progress(self, p: dict) -> None:
        self.summary.setVisible(True)
        self.job_bar.setValue(int(p.get("fraction", 0) * 1000))
        self.job_count.setText(
            f"{p['episodes_done']} of {p['episodes_total']} done")
        self.job_bytes.setText(
            f"{human_bytes(p['bytes_done'])} of {human_bytes(p['bytes_total'])}")
        rate = p.get("rate", 0)
        self.job_rate.setText(human_rate(rate) if rate > 0 else "")
        eta = p.get("eta_seconds", 0)
        self.job_left.setText(f"about {human_eta(eta)} left" if eta > 0 else "")

    def _finished(self, payload: dict) -> None:
        self._set_running(False)
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, _CHK)
            if item:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        self.table.blockSignals(False)

        if payload.get("ok"):
            done = payload.get("done", 0)
            self.job_title.setText(f"Finished — {done} episodes ready")
            self.job_bar.setValue(1000)
            self.job_left.setText("")
            self.job_rate.setText("")
            self.main.log(f"output: {payload.get('output_dir', '')}")
            if self.autosend.isChecked():
                self._autosend(payload.get("output_dir") or self.out_dir.text())
        else:
            self.job_title.setText(f"Stopped — {payload.get('error', 'unknown reason')}")

    def _autosend(self, folder: str) -> None:
        self.main.log(f"Sending everything in {folder}")
        self.send_worker = SendWorker(self.main.current_profile(), folder, parent=self)
        self.send_worker.event.connect(self._autosend_event)
        self.send_worker.done.connect(self._autosend_done)
        retire_on_finish(self.send_worker, lambda: setattr(self, "send_worker", None))
        self.send_worker.start()

    def _autosend_event(self, kind: str, payload: dict) -> None:
        if kind == "send_item_done":
            mark = "sent" if payload["ok"] else "failed"
            self.main.log(f"{payload['name']}: {mark} {payload['detail']}")

    def _autosend_done(self, items: list) -> None:
        ok = sum(1 for i in items if i.get("ok"))
        self.job_title.setText(
            f"{self.job_title.text()} — sent {ok} of {len(items)} to the device")
