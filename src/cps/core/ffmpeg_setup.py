"""Locate ffmpeg/ffprobe, or download a static build on first run.

Resolution order:
  1. an explicit path saved in config ("ffmpeg_dir")
  2. ffmpeg/ffprobe next to a previous download in %APPDATA%\\...\\ffmpeg
  3. ffmpeg/ffprobe on PATH
  4. -> raise FfmpegMissing; the GUI offers "download now" or "browse".

Download source (Windows): gyan.dev "release-essentials" zip, which bundles
ffmpeg.exe + ffprobe.exe. On mac/Linux we only look on PATH (packaging targets
Windows; other platforms are dev-only).
"""
from __future__ import annotations

import io
import os
import shutil
import stat
import sys
import zipfile
from pathlib import Path
from typing import Callable

from . import settings

WIN_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

_EXE = ".exe" if sys.platform == "win32" else ""


class FfmpegMissing(RuntimeError):
    pass


def _config_dir() -> Path | None:
    cfg = settings.load_config()
    d = cfg.get("ffmpeg_dir")
    return Path(d) if d else None


def _candidates() -> list[Path]:
    dirs: list[Path] = []
    cd = _config_dir()
    if cd:
        dirs.append(cd)
    dirs.append(settings.ffmpeg_dir())
    return dirs


def _find(tool: str) -> Path | None:
    name = f"{tool}{_EXE}"
    for d in _candidates():
        p = d / name
        if p.is_file():
            return p
        # gyan zips extract to ffmpeg-*/bin/
        for sub in d.glob(f"ffmpeg-*/bin/{name}"):
            return sub
    onpath = shutil.which(tool)
    return Path(onpath) if onpath else None


def ffmpeg_path() -> Path:
    p = _find("ffmpeg")
    if not p:
        raise FfmpegMissing("ffmpeg not found")
    return p


def ffprobe_path() -> Path:
    p = _find("ffprobe")
    if not p:
        raise FfmpegMissing("ffprobe not found")
    return p


def is_ready() -> bool:
    try:
        ffmpeg_path()
        ffprobe_path()
        return True
    except FfmpegMissing:
        return False


def set_manual_dir(directory: str | Path) -> None:
    d = Path(directory)
    if not (d / f"ffmpeg{_EXE}").is_file():
        raise FfmpegMissing(f"no ffmpeg{_EXE} in {d}")
    cfg = settings.load_config()
    cfg["ffmpeg_dir"] = str(d)
    settings.save_config(cfg)


def _linux_tarball_url() -> str:
    import platform

    arch = platform.machine().lower()
    slug = "arm64" if arch in ("aarch64", "arm64") else "amd64"
    return f"https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-{slug}-static.tar.xz"


def _fetch(url: str, progress: Callable[[int, int], None] | None) -> io.BytesIO:
    import requests

    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        buf = io.BytesIO()
        got = 0
        for chunk in r.iter_content(chunk_size=1 << 16):
            buf.write(chunk)
            got += len(chunk)
            if progress:
                progress(got, total)
    buf.seek(0)
    return buf


def _extract_wanted(names, open_member, dest: Path) -> None:
    """Pull just ffmpeg/ffprobe out of an archive, flattening any directories."""
    wanted = {f"ffmpeg{_EXE}", f"ffprobe{_EXE}"}
    for member in names:
        base = os.path.basename(member)
        if base in wanted:
            src = open_member(member)
            if src is None:
                continue
            with src, open(dest / base, "wb") as out:
                shutil.copyfileobj(src, out)
            os.chmod(dest / base, os.stat(dest / base).st_mode | stat.S_IEXEC)


def download(progress: Callable[[int, int], None] | None = None) -> Path:
    """Fetch a static ffmpeg build into the app's ffmpeg dir. Returns that dir."""
    dest = settings.ffmpeg_dir()

    if sys.platform == "win32":
        buf = _fetch(WIN_ZIP_URL, progress)
        with zipfile.ZipFile(buf) as z:
            _extract_wanted(z.namelist(), z.open, dest)

    elif sys.platform.startswith("linux"):
        import tarfile

        buf = _fetch(_linux_tarball_url(), progress)
        with tarfile.open(fileobj=buf, mode="r:xz") as t:
            _extract_wanted(t.getnames(), t.extractfile, dest)

    elif sys.platform == "darwin":
        # evermeet ships ffmpeg and ffprobe as separate zips. Anything downloaded
        # here carries the macOS quarantine flag, so Homebrew is the smoother path
        # and the GUI recommends it first.
        for url in ("https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip",
                    "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"):
            buf = _fetch(url, progress)
            with zipfile.ZipFile(buf) as z:
                _extract_wanted(z.namelist(), z.open, dest)
    else:
        raise FfmpegMissing(
            f"No automatic ffmpeg download for {sys.platform}. "
            "Install ffmpeg with your package manager."
        )

    if not (dest / f"ffmpeg{_EXE}").is_file():
        raise FfmpegMissing("the download finished but no ffmpeg binary was inside it")
    return dest


def install_hint() -> str:
    """What to tell someone who would rather install ffmpeg themselves."""
    if sys.platform == "darwin":
        return "brew install ffmpeg"
    if sys.platform.startswith("linux"):
        return "sudo apt install ffmpeg   (or your distro's equivalent)"
    return "winget install Gyan.FFmpeg"
