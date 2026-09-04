"""Application paths, small persistent app-settings, and password storage.

Layout under %APPDATA%\\ConsolePrepStudio (or ~/.config/ConsolePrepStudio):

    config.json        profiles + last-used compression settings + app prefs
    state/             one <infohash>.json per torrent job (+ .fastresume, .torrent)
    ffmpeg/            ffmpeg.exe / ffprobe.exe downloaded on first run
    logs/              rolling log files

Passwords are never written to config.json. They go to the OS keyring via
`keyring` under service name "ConsolePrepStudio"; config only stores a reference key.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .. import APP_NAME

KEYRING_SERVICE = APP_NAME


def data_dir() -> Path:
    """Root writable directory for this app."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sub(name: str) -> Path:
    d = data_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_dir() -> Path:
    return _sub("state")


def ffmpeg_dir() -> Path:
    return _sub("ffmpeg")


def logs_dir() -> Path:
    return _sub("logs")


def config_path() -> Path:
    return data_dir() / "config.json"


# --- where the big media folders live ---------------------------------------
# Settings/state/ffmpeg stay in data_dir() so replacing the app folder keeps your
# profiles. downloads/ and output/ sit next to the app, where you can find them.

def app_dir() -> Path:
    """The folder the app itself lives in."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        # a macOS .app bundle: Foo.app/Contents/MacOS/Foo -- writing media inside
        # the bundle is wrong, so hand back the user's Movies folder instead
        if sys.platform == "darwin" and ".app/Contents/MacOS" in str(exe):
            return Path.home() / "Movies" / APP_NAME
        return exe.parent
    return Path(__file__).resolve().parents[3]      # repo root when run from source


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".cps_write_test"
        probe.write_text("", "utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _media_dir(name: str) -> Path:
    beside_app = app_dir() / name
    if _writable(beside_app):
        return beside_app
    fallback = data_dir() / name                     # e.g. app installed read-only
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def default_download_dir() -> Path:
    return _media_dir("downloads")


def default_output_dir() -> Path:
    return _media_dir("output")


def load_config() -> dict[str, Any]:
    p = config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        # keep a copy of the broken file so nothing is silently lost
        try:
            p.rename(p.with_suffix(".json.bad"))
        except OSError:
            pass
        return {}


def save_config(cfg: dict[str, Any]) -> None:
    p = config_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2), "utf-8")
    tmp.replace(p)


# --- password storage -------------------------------------------------------

class NoKeyring(RuntimeError):
    pass


def set_secret(ref: str, value: str) -> None:
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, ref, value)
    except Exception as e:  # noqa: BLE001
        # Linux without gnome-keyring/KWallet is the usual case
        raise NoKeyring(
            "No system keyring is available to store the password. "
            "Install a secret service (gnome-keyring / KWallet) or use an SSH key "
            "file for this profile instead."
        ) from e


def get_secret(ref: str) -> str | None:
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, ref)
    except Exception:
        return None


def delete_secret(ref: str) -> None:
    try:
        import keyring

        keyring.delete_password(KEYRING_SERVICE, ref)
    except Exception:
        pass
