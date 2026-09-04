"""Spawn child processes without flashing a console window.

In a PyInstaller `--windowed` build the app has no console of its own, so every
child process Windows starts (ffmpeg, ffprobe) allocates a fresh one — a black
window pops up for a moment on each call. CREATE_NO_WINDOW suppresses that.
No-op on macOS/Linux.
"""
from __future__ import annotations

import subprocess
import sys

_CREATE_NO_WINDOW = 0x08000000


def no_window_kwargs() -> dict:
    """Extra kwargs for subprocess.run/Popen that keep child consoles hidden."""
    if sys.platform != "win32":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", _CREATE_NO_WINDOW),
        "startupinfo": si,
    }
