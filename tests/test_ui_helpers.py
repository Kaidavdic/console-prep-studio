"""Unit tests for the v2 fixes: ETA formatting, hidden consoles, worker lifetime."""
import subprocess
import sys

import pytest

from cps.core import procutil, settings
from cps.ui.common import human_bytes, human_eta, human_rate


# --- ETA formatting --------------------------------------------------------

@pytest.mark.parametrize("seconds,expected", [
    (0, "—"),
    (-5, "—"),
    (None, "—"),
    (float("inf"), "—"),
    (12, "12s"),
    (270, "4m 30s"),
    (4320, "1h 12m"),
    (90000, "1d 1h"),
])
def test_human_eta(seconds, expected):
    assert human_eta(seconds) == expected


def test_human_rate_unknown_is_dash():
    assert human_rate(0) == "—"
    assert human_rate(3_200_000).endswith("/s")


def test_human_bytes():
    assert human_bytes(0) == "0.0 B"
    assert human_bytes(1536) == "1.5 KB"


# --- no console window on Windows -----------------------------------------

def test_no_window_kwargs_hides_console():
    kw = procutil.no_window_kwargs()
    if sys.platform == "win32":
        assert kw["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert kw["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW
        assert kw["startupinfo"].wShowWindow == subprocess.SW_HIDE
    else:
        assert kw == {}


def test_ffmpeg_subprocesses_use_it():
    """The two places that spawn ffmpeg must both pass the hidden-console kwargs."""
    from cps.core import encoder, ffprobe
    assert "no_window_kwargs()" in _source(encoder._run)
    assert "no_window_kwargs()" in _source(ffprobe.probe)


def _source(fn) -> str:
    import inspect
    return inspect.getsource(fn)


# --- media folders next to the app ----------------------------------------

def test_default_dirs_sit_beside_the_app(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_dir", lambda: tmp_path)
    assert settings.default_download_dir() == tmp_path / "downloads"
    assert settings.default_output_dir() == tmp_path / "output"
    assert (tmp_path / "downloads").is_dir()


def test_default_dirs_fall_back_when_app_dir_is_not_writable(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_dir", lambda: tmp_path / "nope")
    monkeypatch.setattr(settings, "_writable", lambda d: False)
    monkeypatch.setattr(settings, "data_dir", lambda: tmp_path / "appdata")
    assert settings.default_download_dir() == tmp_path / "appdata" / "downloads"


# --- contrast (WCAG 4.5:1 for normal text) --------------------------------

def test_progress_labels_are_readable_on_every_stage_colour():
    """The bar label is drawn over the fill, so it must contrast with it.

    White-on-amber was 2.19:1 before text_on() picked the colour per stage.
    """
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication

    from cps.ui.style import contrast_ratio, stage_color, text_on

    app = QApplication.instance() or QApplication([])
    for win, txt in ((QColor(32, 32, 32), QColor(255, 255, 255)),
                     (QColor(255, 255, 255), QColor(0, 0, 0))):
        pal = QPalette()
        pal.setColor(QPalette.Window, win)
        pal.setColor(QPalette.WindowText, txt)
        app.setPalette(pal)
        for stage in ("queued", "downloading", "converting", "sending", "done", "error"):
            fill = stage_color(stage)
            assert contrast_ratio(text_on(fill), fill) >= 4.5, \
                f"{stage} bar label only reaches {contrast_ratio(text_on(fill), fill):.2f}:1"


def test_secondary_text_is_readable_on_the_app_surfaces():
    """The app paints its own dark background rather than following the system
    theme, so contrast is checked against the surfaces it actually uses."""
    from PySide6.QtGui import QColor

    from cps.ui.theme import C, contrast_ratio

    bg, surface = QColor(C.bg), QColor(C.surface)
    for name, colour in (("text", C.text), ("muted", C.muted)):
        for surf_name, surf in (("bg", bg), ("surface", surface)):
            ratio = contrast_ratio(QColor(colour), surf)
            assert ratio >= 4.5, f"{name} on {surf_name} is only {ratio:.2f}:1"


def test_faint_text_clears_the_large_text_threshold():
    """`faint` is only used for labels under big numbers and placeholder hints,
    so it is held to 3:1 rather than 4.5:1."""
    from PySide6.QtGui import QColor

    from cps.ui.theme import C, contrast_ratio

    assert contrast_ratio(QColor(C.faint), QColor(C.bg)) >= 3.0


def test_accent_button_label_is_readable():
    """White on the accent is text, so 4.5:1. The accent as a filled shape on
    the background is a non-text element, so 3:1 applies there."""
    from PySide6.QtGui import QColor

    from cps.ui.theme import C, contrast_ratio

    for state in (C.accent, C.accent_hi):
        assert contrast_ratio(QColor(C.on_accent), QColor(state)) >= 4.5,             f"{state} label only reaches {contrast_ratio(QColor(C.on_accent), QColor(state)):.2f}:1"
    assert contrast_ratio(QColor(C.accent), QColor(C.bg)) >= 3.0
