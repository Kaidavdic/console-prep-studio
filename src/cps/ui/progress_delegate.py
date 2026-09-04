"""A progress bar drawn straight into a table cell.

Carries three things at once — how far along, which stage, and the numbers —
so a row needs one column instead of three. Painting it (rather than putting a
QProgressBar widget in every cell) keeps a 150-file season pack scrolling
smoothly.

Set on an item:
    Qt.UserRole      float 0..1   how full the bar is
    Qt.UserRole + 1  str          stage name, drives the colour (see style.stage_of)
    Qt.UserRole + 2  str          text drawn inside, e.g. "Converting 72%"
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyledItemDelegate

from .style import stage_color, text_on

FRACTION = Qt.UserRole
STAGE = Qt.UserRole + 1
LABEL = Qt.UserRole + 2

_RADIUS = 3.0


class ProgressDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index) -> None:
        frac = index.data(FRACTION)
        if frac is None:
            super().paint(painter, option, index)
            return

        stage = index.data(STAGE) or "queued"
        label = index.data(LABEL) or ""
        frac = max(0.0, min(1.0, float(frac)))

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(option.rect).adjusted(4, 5, -4, -5)
        colour = stage_color(stage)

        # trough: the stage colour at low opacity, so an empty bar still says
        # which stage the row is waiting on
        trough = QColor(colour)
        trough.setAlpha(38)
        painter.setPen(Qt.NoPen)
        painter.setBrush(trough)
        painter.drawRoundedRect(rect, _RADIUS, _RADIUS)

        fill = QRectF(rect)
        fill.setWidth(rect.width() * frac)
        if frac > 0:
            painter.setBrush(colour)
            painter.drawRoundedRect(fill, _RADIUS, _RADIUS)

        if label:
            # The label sits across both the filled bar and the empty trough,
            # and no single colour is readable on both, so draw it once per
            # region with a colour picked for that background.
            painter.setPen(QPen(option.palette.text().color()))
            painter.setClipRect(rect.adjusted(fill.width(), 0, 0, 0))
            painter.drawText(rect, Qt.AlignCenter, label)

            if frac > 0:
                painter.setPen(QPen(text_on(colour)))
                painter.setClipRect(fill)
                painter.drawText(rect, Qt.AlignCenter, label)
            painter.setClipping(False)

        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), 24))
        return size


def set_progress(item, fraction: float, stage: str, label: str) -> None:
    """Fill in the three roles the delegate reads."""
    item.setData(FRACTION, float(fraction))
    item.setData(STAGE, stage)
    item.setData(LABEL, label)
