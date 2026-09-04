"""The pieces the command-bar layout is built from."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .theme import C, R, S


def heading(text: str, size_delta: float = 0, weight=QFont.DemiBold) -> QLabel:
    lbl = QLabel(text)
    f = lbl.font()
    if size_delta:
        f.setPointSizeF(f.pointSizeF() + size_delta)
    f.setWeight(weight)
    lbl.setFont(f)
    return lbl


def muted(text: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {C.muted};")
    return lbl


def primary(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setProperty("kind", "primary")
    b.setCursor(Qt.PointingHandCursor)
    return b


def ghost(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setProperty("kind", "ghost")
    b.setCursor(Qt.PointingHandCursor)
    return b


def set_kind(button: QPushButton, kind: str) -> None:
    """Restyle a button after the fact — Qt only re-reads a style property on
    an explicit unpolish/polish."""
    button.setProperty("kind", kind)
    button.style().unpolish(button)
    button.style().polish(button)


class Card(QFrame):
    """A raised surface with a hairline. No shadow — shadows on every panel is
    the generic look, and here elevation only needs to say 'this is the input'."""

    def __init__(self, radius: int = R.lg, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {C.surface}; border: 1px solid {C.line};"
            f" border-radius: {radius}px; }}")


class CommandBar(Card):
    """The hero. One big field that takes a magnet link or a dropped .torrent,
    with the device it will prepare for sitting inside it rather than in a
    separate form row.

    The button matters: pressing Enter used to be the only way to read a link,
    which is invisible. The button says what happens next, and Enter still works
    for anyone who expects it.
    """

    submitted = Signal()
    fileDropped = Signal(str)

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent=parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(92)

        self.field = QLineEdit()
        self.field.setProperty("kind", "hero")
        self.field.setStyleSheet(
            f"background: transparent; border: none; font-size: 17px; padding: 0;"
            f" color: {C.text};")
        self.field.setPlaceholderText(placeholder)
        self.field.setClearButtonEnabled(True)
        self.field.returnPressed.connect(self.submitted)

        self.profile = QComboBox()
        self.profile.setCursor(Qt.PointingHandCursor)
        self.profile.setStyleSheet(
            f"QComboBox {{ background: {C.surface_hi}; border: 1px solid {C.line};"
            f" border-radius: {R.pill}px; padding: 5px 12px; color: {C.text}; }}"
            f"QComboBox::drop-down {{ border: none; width: 18px; }}")

        self.load_btn = primary("Load this torrent")
        self.load_btn.setEnabled(False)
        self.load_btn.setDefault(True)
        self.load_btn.clicked.connect(self.submitted)
        self.field.textChanged.connect(
            lambda t: self.load_btn.setEnabled(bool(t.strip())))

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(
            f"color: {C.faint}; background: transparent; border: none;")

        top = QHBoxLayout()
        top.setSpacing(S.md)
        top.addWidget(self.field, 1)
        top.addWidget(self.load_btn)

        for_lbl = muted("for")
        for_lbl.setStyleSheet(
            f"color: {C.faint}; background: transparent; border: none;")

        bottom = QHBoxLayout()
        bottom.setSpacing(S.sm)
        bottom.addWidget(self.hint, 1)
        bottom.addWidget(for_lbl)
        bottom.addWidget(self.profile)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(S.lg, S.md, S.lg, S.md)
        lay.setSpacing(S.sm)
        lay.addLayout(top)
        lay.addLayout(bottom)

    # accepting a dropped .torrent is the fastest path there is
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.setStyleSheet(
                f"QFrame {{ background: {C.surface_hi}; border: 1px solid {C.accent};"
                f" border-radius: {R.lg}px; }}")

    def dragLeaveEvent(self, _e) -> None:
        self._reset_border()

    def dropEvent(self, e) -> None:
        self._reset_border()
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.field.setText(path)
                self.fileDropped.emit(path)
                break

    def _reset_border(self) -> None:
        self.setStyleSheet(
            f"QFrame {{ background: {C.surface}; border: 1px solid {C.line};"
            f" border-radius: {R.lg}px; }}")


class Disclosure(QWidget):
    """“Options” — the settings you touch once, folded away until you want them.

    Keeping paths, ports and toggles on screen permanently is what made the old
    layout feel heavy; none of them change between runs.
    """

    def __init__(self, title: str = "Options", summary: str = "", parent=None):
        super().__init__(parent)
        self._open = False

        self.button = QPushButton(f"⌄  {title}")
        self.button.setProperty("kind", "ghost")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self.toggle)
        self._title = title

        self.summary = QLabel(summary)
        self.summary.setStyleSheet(f"color: {C.faint};")

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(S.sm)
        head.addWidget(self.button)
        head.addWidget(self.summary, 1)

        self.body = QWidget()
        self.body.setVisible(False)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(S.md, S.sm, S.md, S.md)
        self.body_layout.setSpacing(S.sm)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(head)
        lay.addWidget(self.body)

    def add(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self.body_layout.addLayout(layout)

    def toggle(self) -> None:
        self._open = not self._open
        self.body.setVisible(self._open)
        self.button.setText(f"{'⌃' if self._open else '⌄'}  {self._title}")
        self.summary.setVisible(not self._open)

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)


class Segmented(QWidget):
    """A small two- or three-way switch, for picking where files come from."""

    changed = Signal(int)

    def __init__(self, options: list[str], parent=None):
        super().__init__(parent)
        self._buttons: list[QPushButton] = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for i, text in enumerate(options):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, idx=i: self.select(idx))
            self._buttons.append(b)
            lay.addWidget(b)
        lay.addStretch(1)
        self.select(0)

    def select(self, index: int) -> None:
        for i, b in enumerate(self._buttons):
            on = i == index
            b.setChecked(on)
            b.setStyleSheet(
                f"QPushButton {{ background: {C.surface if on else 'transparent'};"
                f" color: {C.text if on else C.muted};"
                f" border: 1px solid {C.line if on else 'transparent'};"
                f" border-radius: {R.sm}px; padding: 5px 14px; }}"
                f"QPushButton:hover {{ color: {C.text}; }}")
        self._index = index
        self.changed.emit(index)

    def current(self) -> int:
        return self._index


class StatStrip(QWidget):
    """The run's numbers: a few large values with quiet labels underneath.

    Size carries the hierarchy, so the labels don't need capitals or separators
    to be legible.
    """

    def __init__(self, fields: list[str], parent=None):
        super().__init__(parent)
        self._values: dict[str, QLabel] = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S.xxl)
        for name in fields:
            col = QVBoxLayout()
            col.setSpacing(1)
            value = QLabel("—")
            f = value.font()
            f.setPointSizeF(f.pointSizeF() + 3)
            f.setWeight(QFont.DemiBold)
            value.setFont(f)
            label = QLabel(name)
            label.setStyleSheet(f"color: {C.faint}; font-size: 11px;")
            col.addWidget(value)
            col.addWidget(label)
            self._values[name] = value
            lay.addLayout(col)
        lay.addStretch(1)

    def set(self, name: str, value: str) -> None:
        if name in self._values:
            self._values[name].setText(value or "—")


class JobStatus(Card):
    """What replaces the command bar once a run starts.

    The top of the window should always answer one question, and which question
    it is depends on whether something is running: 'what do you want to do' or
    'how is it going'. Swapping the two keeps either answer uncluttered.
    """

    def __init__(self, fields: list[str], parent=None):
        super().__init__(parent=parent)
        self.setMinimumHeight(92)

        self.title = heading("", size_delta=2)
        self.title.setStyleSheet(f"color: {C.text}; background: transparent; border: none;")

        self.track = QFrame()
        self.track.setFixedHeight(6)
        self.track.setStyleSheet(
            f"background: {C.line}; border: none; border-radius: 3px;")
        self.fill = QFrame(self.track)
        self.fill.setStyleSheet(
            f"background: {C.accent}; border: none; border-radius: 3px;")
        self.fill.setGeometry(0, 0, 0, 6)
        self._fraction = 0.0

        self.stats = StatStrip(fields)
        self.stats.setStyleSheet("background: transparent; border: none;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(S.lg, S.md, S.lg, S.md)
        lay.setSpacing(S.sm)
        lay.addWidget(self.title)
        lay.addWidget(self.track)
        lay.addWidget(self.stats)

    def set_fraction(self, fraction: float) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        self._resize_fill()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._resize_fill()

    def _resize_fill(self) -> None:
        self.fill.setGeometry(0, 0, int(self.track.width() * self._fraction), 6)

    def set_accent(self, colour: str) -> None:
        self.fill.setStyleSheet(
            f"background: {colour}; border: none; border-radius: 3px;")


class Rule(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background: {C.line}; border: none;")


class NavBar(QWidget):
    """Three destinations, as text. A tab bar's chrome adds nothing here."""

    changed = Signal(int)

    def __init__(self, items: list[str], parent=None):
        super().__init__(parent)
        self._buttons: list[QPushButton] = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(S.xl, S.md, S.xl, 0)
        lay.setSpacing(S.lg)

        title = QLabel("Console Prep Studio")
        tf = title.font()
        tf.setWeight(QFont.DemiBold)
        title.setFont(tf)
        title.setStyleSheet(f"color: {C.text};")
        lay.addWidget(title)
        lay.addSpacing(S.lg)

        for i, text in enumerate(items):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, idx=i: self.select(idx))
            self._buttons.append(b)
            lay.addWidget(b)
        lay.addStretch(1)
        self.select(0)

    def select(self, index: int) -> None:
        for i, b in enumerate(self._buttons):
            on = i == index
            b.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none;"
                f" border-bottom: 2px solid {C.accent if on else 'transparent'};"
                f" color: {C.text if on else C.muted};"
                f" padding: 6px 2px 8px 2px; font-weight: {600 if on else 400}; }}"
                f"QPushButton:hover {{ color: {C.text}; }}")
            b.setChecked(on)
        self.changed.emit(index)
