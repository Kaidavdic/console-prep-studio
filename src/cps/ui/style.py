"""Kept as the old import path; the design language now lives in theme.py."""
from __future__ import annotations

from .theme import (  # noqa: F401
    contrast_ratio, faint_css, muted_css, stage_color, stage_of, stylesheet,
    text_on,
)


def app_stylesheet() -> str:
    return stylesheet()


def is_dark() -> bool:
    return True        # the palette is dark by design now, not by system theme


def muted_color():
    from PySide6.QtGui import QColor

    from .theme import C
    return QColor(C.muted)
