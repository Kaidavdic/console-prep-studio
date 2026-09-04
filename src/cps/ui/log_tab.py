from __future__ import annotations

import time

from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)


class LogTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.view = QPlainTextEdit(readOnly=True)
        self.view.setMaximumBlockCount(5000)
        self.view.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")

        copy_btn = QPushButton("Copy log")
        copy_btn.clicked.connect(self._copy)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.view.clear)

        row = QHBoxLayout()
        row.addWidget(copy_btn)
        row.addWidget(clear_btn)
        row.addStretch(1)

        lay = QVBoxLayout(self)
        lay.addLayout(row)
        lay.addWidget(self.view)

    def append(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        for line in str(msg).rstrip().splitlines() or [""]:
            self.view.appendPlainText(f"{ts}  {line}")

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.view.toPlainText())
