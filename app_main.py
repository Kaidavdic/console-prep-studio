"""Frozen-app entry point (PyInstaller). Kept outside the package so it is run
with a proper top-level import, not as a context-less relative module."""
import multiprocessing
import sys

from cps.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
