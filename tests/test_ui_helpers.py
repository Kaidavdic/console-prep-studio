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
