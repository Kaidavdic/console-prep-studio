"""Start a job: paste a link, tick what you want, go.

The screen answers one question at a time. Before a run that question is "what
do you want to prepare", so the paste field is the whole top of the window and
the settings you set once are folded into Options. Once a run starts the same
space becomes "how is it going", because that is the only thing worth knowing
for the next hour.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core import ffmpeg_setup, settings
from ..core.pipeline import JobConfig
from .common import human_bytes, human_eta, human_rate
from .progress_delegate import ProgressDelegate, set_progress
from .theme import C, S
from .widgets import (
    CommandBar, Disclosure, JobStatus, ghost, muted, primary,
)
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
        self._files: list = []
        self._row_by_fidx: dict[int, int] = {}

        # ---- hero: the command bar, or the running job ----
        self.bar = CommandBar("Paste a magnet link, or drop a .torrent file here")
        self.bar.submitted.connect(self._load)
        self.bar.fileDropped.connect(lambda _p: self._load())
        self.bar.field.textChanged.connect(self._source_changed)
        self.profile = self.bar.profile
        self.source = self.bar.field

        self.status = JobStatus(["done", "downloaded", "speed", "time left"])
        self.hero = QStackedWidget()
        self.hero.addWidget(self.bar)
        self.hero.addWidget(self.status)

        # ---- options: everything you set once ----
        self.opts = Disclosure("Options")
        self.save_dir = QLineEdit(str(settings.default_download_dir()))
        self.out_dir = QLineEdit(str(settings.default_output_dir()))
        self.limit = QSpinBox(); self.limit.setRange(0, 9999)
        self.limit.setSpecialValueText("no limit")
        self.port = QSpinBox(); self.port.setRange(1024, 65535); self.port.setValue(6881)
        self.delete_source = QCheckBox(
            "Delete each source file once it has been converted")
        self.delete_source.setChecked(True)
        self.delete_source.toggled.connect(self._delete_hint)
        self.autosend = QCheckBox("Send to the device when the job finishes")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(S.md)
        form.setVerticalSpacing(S.sm)
        form.addRow("Download to", self._path_row(self.save_dir))
        form.addRow("Converted to", self._path_row(self.out_dir))
        limits = QHBoxLayout()
        limits.addWidget(QLabel("Stop after"))
        limits.addWidget(self.limit)
        limits.addWidget(muted("episodes"))
        limits.addSpacing(S.xl)
        limits.addWidget(QLabel("Port"))
        limits.addWidget(self.port)
        limits.addStretch(1)
        form.addRow("Limits", self._wrap(limits))
        self.opts.add_layout(form)
        self.opts.add(self.delete_source)
        self.opts.add(self.autosend)
        self._delete_hint(True)

        # ---- the list, and the few controls that belong to it ----
        self.count = muted("")
        self.all_btn = ghost("all")
        self.none_btn = ghost("none")
        self.vids_btn = ghost("videos only")
        self.all_btn.clicked.connect(lambda: self._check_all(True))
        self.none_btn.clicked.connect(lambda: self._check_all(False))
        self.vids_btn.clicked.connect(self._check_videos)
        self.pick_row = QWidget()
        pr = QHBoxLayout(self.pick_row)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.addWidget(self.count, 1)
        for b in (self.vids_btn, self.all_btn, self.none_btn):
            pr.addWidget(b)
        self.pick_row.setVisible(False)

        self.table = self._build_table()
        self.empty = QLabel(
            "Paste a magnet link above, or drop a .torrent file onto it.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet(f"color: {C.faint}; padding: 48px;")

        # ---- one primary action ----
        self.start_btn = primary("Start")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = ghost("Stop")
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self._stop)
        self.open_btn = ghost("Open output folder")
        self.open_btn.clicked.connect(self._open_output)
        actions = QHBoxLayout()
        actions.addWidget(self.open_btn)
        actions.addStretch(1)
        actions.addWidget(self.stop_btn)
        actions.addWidget(self.start_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(S.xl, S.lg, S.xl, S.lg)
        lay.setSpacing(S.md)
        lay.addWidget(self.hero)
        lay.addWidget(self.opts)
        lay.addWidget(self.pick_row)
        lay.addWidget(self.empty)
        lay.addWidget(self.table, 1)
        lay.addLayout(actions)

        self.main.profilesChanged.connect(self._reload_profiles)
        self.main.currentProfileChanged.connect(self._sync_profile_combo)
        self.profile.currentIndexChanged.connect(self._profile_picked)
        self._reload_profiles()
        self.table.setVisible(False)

    # ------------------------------------------------------------------
    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    def _path_row(self, edit: QLineEdit) -> QWidget:
        btn = ghost("change")
        btn.clicked.connect(lambda: self._pick_dir(edit))
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(btn)
        return self._wrap(row)

    def _build_table(self) -> QTableWidget:
        t = QTableWidget(0, len(_HEADERS))
        t.setHorizontalHeaderLabels(_HEADERS)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setShowGrid(False)
        t.setItemDelegateForColumn(_PROG, ProgressDelegate(t))
        t.itemChanged.connect(self._on_item_changed)
        h = t.horizontalHeader()
        h.setSectionResizeMode(_CHK, QHeaderView.Fixed); t.setColumnWidth(_CHK, 30)
        h.setSectionResizeMode(_EP, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(_NAME, QHeaderView.Stretch)
        h.setSectionResizeMode(_SIZE, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(_PROG, QHeaderView.Fixed); t.setColumnWidth(_PROG, 180)
        h.setSectionResizeMode(_SPEED, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(_LEFT, QHeaderView.ResizeToContents)
        return t

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
        self.opts.set_summary(
            "one file on disk at a time" if on else "sources kept for seeding")

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
        self.table.setVisible(False)
        self.pick_row.setVisible(False)
        self.empty.setVisible(True)
        self.empty.setText("Paste a magnet link above, or drop a .torrent file onto it.")
        self.start_btn.setEnabled(False)
        self.bar.hint.setText("")

    # -- reading the torrent -------------------------------------------
    def _load(self) -> None:
        src = self.source.text().strip()
        if not src:
            return
        if not src.startswith("magnet:") and not Path(src).is_file():
            self.bar.hint.setText("That file does not exist")
            return
        self.bar.hint.setText("Reading the torrent…")
        self.empty.setText("Reading the torrent…")
        self.meta_worker = MetadataWorker(src, port=self.port.value(),
                                          regex=self.main.current_profile().episode_regex,
                                          parent=self)
        self.meta_worker.status.connect(self.bar.hint.setText)
        self.meta_worker.files_ready.connect(self._show_files)
        self.meta_worker.failed.connect(self._load_failed)
        retire_on_finish(self.meta_worker, lambda: setattr(self, "meta_worker", None))
        self.meta_worker.start()

    def _load_failed(self, err: str) -> None:
        self.bar.hint.setText("Could not read that torrent")
        self.empty.setText(
            "A magnet link needs peers before it can hand over its file list.\n"
            "Try again in a moment, or use a .torrent file.")
        self.main.log(f"load failed: {err}")

    def _show_files(self, files: list) -> None:
        self._files = files
        self._row_by_fidx = {f.index: row for row, f in enumerate(files)}
        self.bar.hint.setText("")

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
                name.setForeground(Qt.gray)
            self.table.setItem(row, _NAME, name)

            size = QTableWidgetItem(human_bytes(f.size))
            size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, _SIZE, size)

            prog = QTableWidgetItem()
            set_progress(prog, 0.0, "queued", "" if f.is_video else "skipped")
            self.table.setItem(row, _PROG, prog)
            for col in (_SPEED, _LEFT):
                cell = QTableWidgetItem("")
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, col, cell)
        self.table.blockSignals(False)

        self.empty.setVisible(False)
        self.table.setVisible(True)
        self.pick_row.setVisible(True)
        self.start_btn.setEnabled(True)
        self._update_selection_summary()

    # -- selection ------------------------------------------------------
    def _checked_rows(self) -> list[int]:
        return [r for r in range(self.table.rowCount())
                if self.table.item(r, _CHK)
                and self.table.item(r, _CHK).checkState() == Qt.Checked]

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == _CHK and not self.worker:
            cell = self.table.item(item.row(), _PROG)
            if cell:
                picked = item.checkState() == Qt.Checked
                set_progress(cell, 0.0, "queued", "" if picked else "skipped")
            self._update_selection_summary()

    def _update_selection_summary(self) -> None:
        rows = self._checked_rows()
        total = sum(self._files[r].size for r in rows) if self._files else 0
        self.count.setText(
            f"{len(rows)} of {len(self._files)} files    {human_bytes(total)}")

    def _check_all(self, on: bool) -> None:
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            self.table.item(r, _CHK).setCheckState(Qt.Checked if on else Qt.Unchecked)
            set_progress(self.table.item(r, _PROG), 0.0, "queued", "" if on else "skipped")
        self.table.blockSignals(False)
        self.table.viewport().update()
        self._update_selection_summary()

    def _check_videos(self) -> None:
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            keep = self._files[r].is_video
            self.table.item(r, _CHK).setCheckState(Qt.Checked if keep else Qt.Unchecked)
            set_progress(self.table.item(r, _PROG), 0.0, "queued", "" if keep else "skipped")
        self.table.blockSignals(False)
        self.table.viewport().update()
        self._update_selection_summary()

    # -- running --------------------------------------------------------
    def _start(self) -> None:
        rows = self._checked_rows()
        if not self._files or not rows:
            return
        if not ffmpeg_setup.is_ready():
            from .ffmpeg_dialog import ensure_ffmpeg
            if not ensure_ffmpeg(self):
                return

        cfg = JobConfig(
            source=self.source.text().strip(),
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
                         "" if picked else "skipped")
        self.table.blockSignals(False)
        self.table.viewport().update()

        self.status.title.setText(self._torrent_name())
        self.status.set_fraction(0.0)
        self.hero.setCurrentWidget(self.status)
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
        retire_on_finish(w, self._release_worker)
        w.start()

    def _torrent_name(self) -> str:
        if not self._files:
            return "Job"
        first = Path(self._files[0].path)
        return first.parts[0] if len(first.parts) > 1 else first.stem

    def _release_worker(self) -> None:
        self.worker = None

    def _stop(self) -> None:
        if self.worker:
            self.status.title.setText("Stopping after the current step…")
            self.worker.request_stop()
            self.stop_btn.setEnabled(False)

    def _set_running(self, running: bool) -> None:
        self.start_btn.setVisible(not running)
        self.stop_btn.setVisible(running)
        self.stop_btn.setEnabled(running)
        self.opts.setEnabled(not running)
        for b in (self.all_btn, self.none_btn, self.vids_btn):
            b.setEnabled(not running)

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
        for r in self._checked_rows():
            if r not in planned:
                self._set_row(r, 0.0, "skipped", "no episode found")

    def _update_episode(self, e: dict) -> None:
        row = self._row_for(e["file_index"])
        if row is None:
            return
        status = e["status"]
        if status == "done":
            self._set_row(row, 1.0, "done", "done")
        elif status == "error":
            self._set_row(row, 0.0, "error", "failed")
            self.table.item(row, _NAME).setToolTip(e.get("error", ""))
        elif status == "downloading":
            self._set_row(row, 0.0, "downloading", "waiting")

    def _dl_progress(self, p: dict) -> None:
        row = self._row_for(p["file_index"])
        if row is None:
            return
        pct = p["fraction"] * 100
        stalled = p.get("stalled_seconds", 0)
        if p["fraction"] >= 1.0:
            self._set_row(row, 1.0, "downloading", "downloaded")
        elif stalled:
            self._set_row(row, p["fraction"],
                          "error" if stalled > 120 else "downloading",
                          f"waiting for peers  {pct:.0f}%",
                          f"{p.get('peers', 0)} peers", "—")
        else:
            self._set_row(row, p["fraction"], "downloading", f"{pct:.0f}%",
                          human_rate(p.get("rate", 0)),
                          human_eta(p.get("eta_seconds", 0)))

    def _enc_progress(self, p: dict) -> None:
        row = self._row_for(p["file_index"])
        if row is None:
            return
        speed = p.get("speed_x") or 0
        self._set_row(row, p["fraction"], "converting",
                      f"converting  {p['fraction'] * 100:.0f}%",
                      f"{speed:.1f}x" if speed else "",
                      human_eta(p.get("eta_seconds", 0)))

    def _job_progress(self, p: dict) -> None:
        self.status.set_fraction(p.get("fraction", 0))
        self.status.stats.set("done", f"{p['episodes_done']} of {p['episodes_total']}")
        self.status.stats.set("downloaded",
                              f"{human_bytes(p['bytes_done'])} of {human_bytes(p['bytes_total'])}")
        rate = p.get("rate", 0)
        self.status.stats.set("speed", human_rate(rate) if rate > 0 else "—")
        eta = p.get("eta_seconds", 0)
        self.status.stats.set("time left", human_eta(eta))

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
            self.status.title.setText(f"Finished — {done} episodes ready")
            self.status.set_fraction(1.0)
            self.status.set_accent(C.done)
            self.status.stats.set("speed", "—")
            self.status.stats.set("time left", "—")
            self.main.log(f"output: {payload.get('output_dir', '')}")
            if self.autosend.isChecked():
                self._autosend(payload.get("output_dir") or self.out_dir.text())
        else:
            self.status.title.setText(f"Stopped — {payload.get('error', 'unknown reason')}")
            self.status.set_accent(C.error)

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
        self.status.title.setText(
            f"{self.status.title.text()} — sent {ok} of {len(items)}")
