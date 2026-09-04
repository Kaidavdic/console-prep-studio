from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core import settings
from .common import human_bytes, human_eta, human_rate
from .progress_delegate import ProgressDelegate, set_progress
from .style import muted_css
from .worker import SendWorker, retire_on_finish

_CHK, _NAME, _SIZE, _PROG, _RESULT = range(5)
_HEADERS = ["", "File", "Size", "Progress", "Result"]


class SendTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.worker: SendWorker | None = None
        self._paths: list[Path] = []             # one per row
        self._row_by_name: dict[str, int] = {}
        self._sent_bytes = 0
        self._batch_bytes = 0
        self._started = 0.0
        self._current_row: int | None = None

        self.folder = QLineEdit(str(settings.default_output_dir()))
        self.folder.textChanged.connect(self._scan)
        pick = QPushButton("Browse…")
        pick.clicked.connect(self._pick)
        self.profile = QComboBox()

        top = QHBoxLayout()
        top.addWidget(QLabel("Folder"))
        top.addWidget(self.folder, 1)
        top.addWidget(pick)
        top.addSpacing(16)
        top.addWidget(QLabel("Send to"))
        top.addWidget(self.profile)

        self.send_btn = QPushButton("Send selected")
        self.send_btn.clicked.connect(self._send)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        self.all_btn = QPushButton("Select all")
        self.all_btn.clicked.connect(lambda: self._check_all(True))
        self.none_btn = QPushButton("Select none")
        self.none_btn.clicked.connect(lambda: self._check_all(False))
        self.scan_btn = QPushButton("Refresh")
        self.scan_btn.clicked.connect(self._scan)
        btns = QHBoxLayout()
        btns.addWidget(self.send_btn)
        btns.addWidget(self.stop_btn)
        btns.addSpacing(24)
        btns.addWidget(self.all_btn)
        btns.addWidget(self.none_btn)
        btns.addStretch(1)
        btns.addWidget(self.scan_btn)

        self.summary = self._build_summary()

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # matches the other two lists: hairline separators, no second row colour
        self.table.setShowGrid(False)
        self.table.setItemDelegateForColumn(_PROG, ProgressDelegate(self.table))
        self.table.itemChanged.connect(self._on_item_changed)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(_CHK, QHeaderView.Fixed)
        self.table.setColumnWidth(_CHK, 28)
        head.setSectionResizeMode(_NAME, QHeaderView.Stretch)
        head.setSectionResizeMode(_SIZE, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(_PROG, QHeaderView.Fixed)
        self.table.setColumnWidth(_PROG, 190)
        head.setSectionResizeMode(_RESULT, QHeaderView.ResizeToContents)

        self.empty_hint = QLabel()
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setStyleSheet(muted_css() + " padding: 28px;")

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(btns)
        lay.addWidget(self.summary)
        lay.addWidget(self.empty_hint, 1)     # takes the slack while the list is empty
        lay.addWidget(self.table, 1)

        self.main.profilesChanged.connect(self._reload_profiles)
        self._reload_profiles()
        self._scan()

    # ------------------------------------------------------------------
    def _build_summary(self) -> QFrame:
        box = QFrame()
        box.setFrameShape(QFrame.StyledPanel)
        self.title = QLabel("Nothing sent yet")
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
        self.rate = QLabel("")
        self.left = QLabel("")
        for w in (self.count, self.bytes, self.rate, self.left):
            w.setStyleSheet(muted_css())

        grid = QGridLayout(box)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(28)
        grid.addWidget(self.title, 0, 0, 1, 4)
        grid.addWidget(self.bar, 1, 0, 1, 4)
        grid.addWidget(self.count, 2, 0)
        grid.addWidget(self.bytes, 2, 1)
        grid.addWidget(self.rate, 2, 2)
        grid.addWidget(self.left, 2, 3)
        grid.setColumnStretch(3, 1)
        return box

    def _reload_profiles(self) -> None:
        cur = self.profile.currentData()
        self.profile.blockSignals(True)
        self.profile.clear()
        for p in self.main.profiles:
            self.profile.addItem(p.name, p.id)
        if cur:
            for i in range(self.profile.count()):
                if self.profile.itemData(i) == cur:
                    self.profile.setCurrentIndex(i)
        self.profile.blockSignals(False)

    def _pick(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose the folder to send from",
                                             self.folder.text())
        if d:
            self.folder.setText(d)

    # -- listing --------------------------------------------------------
    def _scan(self) -> None:
        if self.worker:
            return
        from ..core.sender import collect
        folder = Path(self.folder.text())
        self._paths = collect(folder) if folder.exists() else []

        self.table.blockSignals(True)
        self.table.setRowCount(len(self._paths))
        self._row_by_name.clear()
        for row, f in enumerate(self._paths):
            self._row_by_name[f.name] = row
            chk = QTableWidgetItem()
            chk.setFlags((chk.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
            chk.setCheckState(Qt.Checked)
            self.table.setItem(row, _CHK, chk)

            name = QTableWidgetItem(f.name)
            name.setToolTip(str(f))
            self.table.setItem(row, _NAME, name)

            size = QTableWidgetItem(human_bytes(f.stat().st_size))
            size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, _SIZE, size)

            prog = QTableWidgetItem()
            set_progress(prog, 0.0, "queued", "Ready")
            self.table.setItem(row, _PROG, prog)
            self.table.setItem(row, _RESULT, QTableWidgetItem(""))
        self.table.blockSignals(False)

        has = bool(self._paths)
        self.table.setVisible(has)
        self.empty_hint.setVisible(not has)
        typed = self.folder.text().strip()
        if typed and not Path(typed).is_dir():
            self.empty_hint.setText("That folder isn't there any more.\n"
                                    "Press Browse… and pick one that is.")
        else:
            self.empty_hint.setText(
                "Nothing converted yet.\n"
                "Convert some videos first — “From a torrent” or “From a folder” "
                "at the top of this screen — or press Browse… to send from "
                "somewhere else.")
        self._update_selection_summary()

    def _checked_rows(self) -> list[int]:
        return [r for r in range(self.table.rowCount())
                if self.table.item(r, _CHK)
                and self.table.item(r, _CHK).checkState() == Qt.Checked]

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == _CHK and not self.worker:
            cell = self.table.item(item.row(), _PROG)
            picked = item.checkState() == Qt.Checked
            if cell:
                set_progress(cell, 0.0, "queued", "Ready" if picked else "Not selected")
            self._update_selection_summary()

    def _update_selection_summary(self) -> None:
        rows = self._checked_rows()
        total = sum(self._paths[r].stat().st_size for r in rows)
        self.title.setText("Ready to send" if rows else "Nothing selected")
        self.bar.setValue(0)
        self.count.setText(f"{len(rows)} of {len(self._paths)} files")
        self.bytes.setText(human_bytes(total))
        self.rate.setText("")
        self.left.setText("")

    def _check_all(self, on: bool) -> None:
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            self.table.item(r, _CHK).setCheckState(Qt.Checked if on else Qt.Unchecked)
            set_progress(self.table.item(r, _PROG), 0.0, "queued",
                         "Ready" if on else "Not selected")
        self.table.blockSignals(False)
        self.table.viewport().update()
        self._update_selection_summary()

    # -- sending --------------------------------------------------------
    def _send(self) -> None:
        pid = self.profile.currentData()
        profile = next((p for p in self.main.profiles if p.id == pid), None)
        if not profile:
            return
        rows = self._checked_rows()
        if not rows:
            self.title.setText("Tick at least one file to send")
            return

        files = [self._paths[r] for r in rows]
        self._batch_bytes = sum(f.stat().st_size for f in files)
        self._sent_bytes = 0
        self._started = time.monotonic()
        self._current_row = None

        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, _CHK)
            item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            self.table.setItem(r, _RESULT, QTableWidgetItem(""))
            set_progress(self.table.item(r, _PROG), 0.0,
                         "queued" if r in rows else "skipped",
                         "Queued" if r in rows else "Not selected")
        self.table.blockSignals(False)
        self.table.viewport().update()

        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.all_btn.setEnabled(False)
        self.none_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.title.setText(f"Sending to {profile.name}")

        self.worker = SendWorker(profile, self.folder.text(), files=files, parent=self)
        self.worker.event.connect(self._on_event)
        self.worker.done.connect(self._on_done)
        retire_on_finish(self.worker, self._release_worker)
        self.worker.start()

    def _release_worker(self) -> None:
        self.worker = None

    def _stop(self) -> None:
        if self.worker:
            self.title.setText("Stopping after the current file…")
            self.worker.request_stop()
            self.stop_btn.setEnabled(False)

    def _on_event(self, kind: str, payload: dict) -> None:
        if kind == "send_item_start":
            self._current_row = self._row_by_name.get(payload["name"])
        elif kind == "send_progress":
            row = self._row_by_name.get(payload["name"])
            total = payload.get("total") or 0
            if row is not None and total:
                frac = payload["done"] / total
                set_progress(self.table.item(row, _PROG), frac, "sending",
                             f"Sending {frac * 100:.0f}%")
                self.table.viewport().update()
                self._update_live(payload["done"])
        elif kind == "send_item_done":
            row = self._row_by_name.get(payload["name"])
            if row is not None:
                ok = payload["ok"]
                set_progress(self.table.item(row, _PROG), 1.0 if ok else 0.0,
                             "done" if ok else "error", "Sent" if ok else "Failed")
                self.table.item(row, _RESULT).setText(
                    "verified" if ok else payload.get("detail", "failed"))
                self.table.item(row, _RESULT).setToolTip(payload.get("detail", ""))
                self._sent_bytes += self._paths[row].stat().st_size
                self.table.viewport().update()
            self._update_live(0)
        elif kind == "send_done":
            hook = (payload.get("hook") or "").strip()
            if hook:
                self.main.log(f"Device replied: {hook}")
        elif kind == "log":
            self.main.log(payload.get("msg", ""))

    def _update_live(self, current_file_done: int) -> None:
        done = self._sent_bytes + current_file_done
        elapsed = max(0.001, time.monotonic() - self._started)
        rate = done / elapsed
        self.bar.setValue(int(done / self._batch_bytes * 1000) if self._batch_bytes else 0)
        self.bytes.setText(f"{human_bytes(done)} of {human_bytes(self._batch_bytes)}")
        self.rate.setText(human_rate(rate))
        remaining = self._batch_bytes - done
        self.left.setText(
            f"about {human_eta(remaining / rate)} left" if rate > 1 and remaining > 0 else "")

    def _on_done(self, items: list) -> None:
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        for b in (self.all_btn, self.none_btn, self.scan_btn):
            b.setEnabled(True)
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, _CHK)
            if item:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        self.table.blockSignals(False)

        ok = sum(1 for i in items if i.get("ok"))
        failed = len(items) - ok
        self.bar.setValue(1000 if failed == 0 and items else self.bar.value())
        self.title.setText(
            f"Sent {ok} of {len(items)} files" if not failed
            else f"Sent {ok} of {len(items)} files, {failed} failed")
        self.count.setText(f"{ok} on the device")
        self.rate.setText("")
        self.left.setText("")
