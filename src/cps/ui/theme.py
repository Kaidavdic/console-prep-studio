"""The app's visual language, as tokens plus one stylesheet built from them.

Shape of the idea: this is a tool you point at something and then leave running
for hours. So the screen has exactly one job at a time — take a link, or show
what's happening — and everything you set once lives behind a disclosure.

Chrome is deliberately quiet because the row progress bars are the information
system, and three hues (downloading / converting / done) only read clearly
against a neutral surface. The accent is a violet that none of those three use,
so "the thing you can press" never competes with "the thing that is happening".
"""
from __future__ import annotations

from PySide6.QtGui import QColor


class C:
    """Colour tokens. Dark-first; the light set keeps the same roles."""
    bg = "#0F1115"          # window
    surface = "#161A21"     # raised panels, the command bar
    surface_hi = "#1D222B"  # hover
    line = "#232935"        # hairlines, never a heavy border
    text = "#E6E9EF"
    muted = "#8B93A3"
    faint = "#5D6472"

    # Darkened from the first pick so white sits on it at 4.79:1. As a filled
    # shape against the background it still clears 3:1, which is the threshold
    # that applies to a non-text UI element.
    accent = "#6E5CEA"      # the one interactive colour
    accent_hi = "#6250DC"   # hover deepens; lightening it would fail white text
    accent_dim = "#3E3576"  # disabled
    on_accent = "#FFFFFF"

    # stage colours: three clearly different hues, readable side by side
    queued = "#6B7280"
    downloading = "#3B9EE5"
    converting = "#E0A44A"
    sending = "#2DB4C4"
    done = "#43B581"
    error = "#E5615A"


class S:
    """Spacing scale. Multiples of 4, used everywhere so rhythm is consistent."""
    xs, sm, md, lg, xl, xxl = 4, 8, 12, 16, 24, 32


class R:
    """Corner radii. Small for controls, larger for the hero."""
    sm, md, lg, pill = 4, 8, 14, 999


STAGE = {
    "queued": C.queued,
    "downloading": C.downloading,
    "converting": C.converting,
    "sending": C.sending,
    "done": C.done,
    "error": C.error,
    "skipped": C.faint,
}


def stage_color(stage: str) -> QColor:
    return QColor(STAGE.get(stage, C.queued))


def stage_of(status: str) -> str:
    s = (status or "").lower()
    for key in ("error", "converting", "downloading", "sending", "done", "skipped"):
        if s.startswith(key):
            return key
    return "queued"


# --- contrast helpers ------------------------------------------------------

def _luminance(c: QColor) -> float:
    def ch(v: int) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast_ratio(a: QColor, b: QColor) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def text_on(background: QColor) -> QColor:
    """Black or white, whichever is readable on this background.

    Stage colours are mid-tone, so a fixed white label falls to ~2.2:1 on the
    amber bar. Choose per background instead of assuming.
    """
    white, black = QColor("#FFFFFF"), QColor("#000000")
    return white if contrast_ratio(white, background) >= contrast_ratio(black, background) else black


def muted_css() -> str:
    return f"color: {C.muted};"


def faint_css() -> str:
    return f"color: {C.faint};"


def stylesheet() -> str:
    """One sheet for the whole app, written from the tokens above."""
    return f"""
    QWidget {{
        background: {C.bg};
        color: {C.text};
        font-size: 13px;
    }}
    QToolTip {{
        background: {C.surface_hi};
        color: {C.text};
        border: 1px solid {C.line};
        padding: {S.xs}px {S.sm}px;
        border-radius: {R.sm}px;
    }}

    /* --- buttons: one accent, everything else recedes --------------- */
    QPushButton {{
        background: {C.surface};
        color: {C.text};
        border: 1px solid {C.line};
        border-radius: {R.sm}px;
        padding: 7px 14px;
    }}
    QPushButton:hover  {{ background: {C.surface_hi}; }}
    QPushButton:pressed{{ background: {C.bg}; }}
    QPushButton:disabled {{ color: {C.faint}; background: {C.bg}; border-color: {C.line}; }}

    QPushButton[kind="primary"] {{
        background: {C.accent};
        color: {C.on_accent};
        border: none;
        border-radius: {R.md}px;
        padding: 10px 26px;
        font-weight: 600;
    }}
    QPushButton[kind="primary"]:hover    {{ background: {C.accent_hi}; }}
    QPushButton[kind="primary"]:disabled {{ background: {C.accent_dim}; color: #B9B2E8; }}

    QPushButton[kind="ghost"] {{
        background: transparent;
        border: none;
        color: {C.muted};
        padding: 5px 10px;
    }}
    QPushButton[kind="ghost"]:hover {{ color: {C.text}; background: {C.surface}; }}

    /* --- inputs ------------------------------------------------------ */
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
        background: {C.surface};
        border: 1px solid {C.line};
        border-radius: {R.sm}px;
        padding: 6px 9px;
        selection-background-color: {C.accent};
        selection-color: {C.on_accent};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
        border-color: {C.accent};
    }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {C.faint}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{
        background: {C.surface};
        border: 1px solid {C.line};
        selection-background-color: {C.accent};
        outline: none;
    }}

    QLineEdit[kind="hero"] {{
        background: transparent;
        border: none;
        font-size: 17px;
        padding: 0;
    }}

    /* --- tables: no grid, no chrome, the rows are the content ------- */
    QTableWidget {{
        background: transparent;
        border: none;
        gridline-color: transparent;
        outline: none;
    }}
    QTableWidget::item {{
        padding: 8px 6px;
        border-bottom: 1px solid {C.line};
    }}
    QTableWidget::item:selected {{ background: {C.surface}; color: {C.text}; }}
    QHeaderView::section {{
        background: transparent;
        color: {C.faint};
        border: none;
        border-bottom: 1px solid {C.line};
        padding: 6px;
        font-weight: 500;
    }}
    QTableCornerButton::section {{ background: transparent; border: none; }}

    /* --- scrollbars: present only while relevant --------------------- */
    QScrollBar:vertical   {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: {C.line}; border-radius: 5px; min-height: 28px; min-width: 28px;
    }}
    QScrollBar::handle:hover {{ background: {C.faint}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    /* --- misc -------------------------------------------------------- */
    QProgressBar {{
        border: none; border-radius: 3px; background: {C.line}; text-align: center;
    }}
    QProgressBar::chunk {{ border-radius: 3px; background: {C.accent}; }}

    /* --- grouped settings -------------------------------------------- */
    QGroupBox {{
        border: none;
        border-top: 1px solid {C.line};
        margin-top: {S.lg}px;
        padding-top: {S.lg}px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 0px;
        padding: 0 0 {S.sm}px 0;
        color: {C.muted};
        font-weight: 600;
    }}

    /* Qt cannot draw CSS-style border triangles, so styled spin arrows come
       out as grey bars. Drop the buttons: these values are typed, and the
       wheel and arrow keys still step them. */
    QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
    QSpinBox {{ padding-right: 9px; }}

    QCheckBox {{ spacing: {S.sm}px; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border: 1px solid {C.faint};
        border-radius: {R.sm}px;
        background: {C.surface};
    }}
    QCheckBox::indicator:checked {{
        background: {C.accent};
        border-color: {C.accent};
        image: none;
    }}
    QCheckBox::indicator:hover {{ border-color: {C.accent}; }}

    /* checkboxes drawn inside table cells are a different primitive */
    QTableView::indicator {{
        width: 15px; height: 15px;
        border: 1px solid {C.faint};
        border-radius: {R.sm}px;
        background: {C.surface};
    }}
    QTableView::indicator:checked {{
        background: {C.accent};
        border-color: {C.accent};
    }}
    QTableView::indicator:hover {{ border-color: {C.accent}; }}

    QListWidget {{
        background: {C.surface}; border: 1px solid {C.line};
        border-radius: {R.sm}px; outline: none;
    }}
    QListWidget::item {{ padding: 7px 9px; border-radius: {R.sm}px; }}
    QListWidget::item:selected {{ background: {C.accent}; color: {C.on_accent}; }}

    QStatusBar {{ background: {C.bg}; color: {C.faint}; border-top: 1px solid {C.line}; }}
    QStatusBar::item {{ border: none; }}
    QSplitter::handle {{ background: {C.line}; }}
    QDialog {{ background: {C.bg}; }}
    """
