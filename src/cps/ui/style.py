"""Visual language for the app.

Every row here moves through two stages — download, then convert — which is the
thing this tool has that a plain torrent client doesn't. So stage is carried by
colour and by a word inside the row's progress bar, and that bar is the only
loud element on the screen. Surfaces come from the system palette so the app
follows the Windows/macOS/Linux light or dark theme instead of fighting it.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# stage -> (light theme, dark theme). Distinct hues, not shades of one colour,
# so you can tell downloading from converting out of the corner of your eye.
_STAGE = {
    "queued":     ("#9AA0A6", "#7C8288"),
    "downloading": ("#3B82C4", "#5AA0DC"),
    "converting": ("#C8862B", "#E0A44A"),
    "sending":    ("#6A5ACD", "#8E80E0"),
    "done":       ("#3E8E5A", "#57AE74"),
    "error":      ("#C0453B", "#E0655B"),
    "skipped":    ("#9AA0A6", "#6B7075"),
}


def is_dark() -> bool:
    app = QApplication.instance()
    if app is None:
        return False
    return app.palette().color(QPalette.Window).lightness() < 128


def stage_color(stage: str) -> QColor:
    light, dark = _STAGE.get(stage, _STAGE["queued"])
    return QColor(dark if is_dark() else light)


def _relative_luminance(c: QColor) -> float:
    def channel(v: int) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return (0.2126 * channel(c.red()) + 0.7152 * channel(c.green())
            + 0.0722 * channel(c.blue()))


def contrast_ratio(a: QColor, b: QColor) -> float:
    """WCAG contrast between two colours, 1:1 (identical) to 21:1 (black/white)."""
    hi, lo = sorted((_relative_luminance(a), _relative_luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def text_on(background: QColor) -> QColor:
    """Black or white, whichever is actually readable on this background.

    The stage colours are mid-tone by design, so white text on a filled bar can
    fall to about 2.2:1 — under the 4.5:1 minimum. Pick per background instead
    of assuming the palette's text colour works everywhere.
    """
    white, black = QColor("#ffffff"), QColor("#000000")
    return white if contrast_ratio(white, background) >= contrast_ratio(black, background) else black


def muted_color() -> QColor:
    """Secondary text: readable but clearly subordinate, in either theme.

    `palette(mid)` is a border colour, not a text colour — on a dark theme it
    comes out almost invisible — so blend the real text colour toward the
    background instead.
    """
    app = QApplication.instance()
    if app is None:
        return QColor("#808080")
    pal = app.palette()
    text = pal.color(QPalette.WindowText)
    back = pal.color(QPalette.Window)
    mix = 0.42                       # keeps roughly a 4.5:1 contrast either way
    return QColor(
        round(text.red() * (1 - mix) + back.red() * mix),
        round(text.green() * (1 - mix) + back.green() * mix),
        round(text.blue() * (1 - mix) + back.blue() * mix),
    )


def muted_css() -> str:
    return f"color: {muted_color().name()};"


def stage_of(status: str) -> str:
    """Map a status string from the pipeline onto a stage colour."""
    s = (status or "").lower()
    for key in ("error", "converting", "downloading", "sending", "done", "skipped"):
        if s.startswith(key):
            return key
    return "queued"


def app_stylesheet() -> str:
    """Small, restrained sheet: breathing room in tables, quiet headers.

    Deliberately sets no background colours — the system palette owns those, so
    this reads correctly in both light and dark without a second theme.
    """
    return """
    QTableWidget {
        gridline-color: palette(midlight);
        selection-background-color: palette(highlight);
        alternate-background-color: palette(alternate-base);
    }
    QTableWidget::item { padding: 5px 6px; }
    QHeaderView::section {
        padding: 6px 8px;
        border: none;
        border-bottom: 1px solid palette(mid);
        font-weight: 600;
    }
    QTabBar::tab { padding: 7px 16px; }
    QPushButton { padding: 5px 14px; }
    QLineEdit, QComboBox, QSpinBox { padding: 4px 6px; }
    QGroupBox {
        border: 1px solid palette(mid);
        border-radius: 4px;
        margin-top: 9px;
        padding-top: 8px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 4px;
    }
    QProgressBar {
        border: none;
        border-radius: 3px;
        background: palette(alternate-base);
    }
    QProgressBar::chunk {
        border-radius: 3px;
        background: %s;
    }
    """ % stage_color("downloading").name()
