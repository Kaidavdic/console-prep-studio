"""Leave a trace when the app dies.

A --windowed PyInstaller build has no console, so an unhandled exception or a hard
abort disappears silently — which is exactly what happened when a QThread was
destroyed mid-run. Everything here funnels into %APPDATA%\\ConsolePrepStudio\\logs.
"""
from __future__ import annotations

import atexit
import faulthandler
import sys
import threading
import traceback
from datetime import datetime

from ..core import settings

_fault_file = None


def _log_path():
    return settings.logs_dir() / "crash.log"


def _write(header: str, body: str) -> None:
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S}  {header} =====\n")
            f.write(body)
            f.write("\n")
    except OSError:
        pass


def install() -> None:
    global _fault_file

    def excepthook(exc_type, exc, tb) -> None:
        _write("unhandled exception", "".join(traceback.format_exception(exc_type, exc, tb)))
        sys.__excepthook__(exc_type, exc, tb)

    def threadhook(args) -> None:
        _write(f"unhandled exception in thread {args.thread and args.thread.name}",
               "".join(traceback.format_exception(args.exc_type, args.exc_value,
                                                  args.exc_traceback)))

    sys.excepthook = excepthook
    threading.excepthook = threadhook

    # catches hard aborts (segfault, std::terminate) that no Python hook can see
    try:
        _fault_file = open(settings.logs_dir() / "faulthandler.log", "a", encoding="utf-8")
        faulthandler.enable(file=_fault_file)
        atexit.register(_fault_file.close)
    except OSError:
        pass
