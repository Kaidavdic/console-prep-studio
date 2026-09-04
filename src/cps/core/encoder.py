"""Build and run the ffmpeg command for one episode.

Ported from prep-for-knulli.sh. Two output flavours:

  burn-in  ->  <title> [burned-in subs].mp4   subs rendered into the picture
  soft     ->  <title>.<container>             one default subtitle track + fonts

Video is always re-encoded (x264/x265, CRF) and scaled to the profile panel size.
Audio is downmixed to the chosen codec/bitrate/channels and tagged with the
source language.
"""
from __future__ import annotations

import contextlib
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from . import ffmpeg_setup
from .ffprobe import Probe, Stream
from .procutil import no_window_kwargs
from .profiles import Compression

_PROGRESS_TIME = re.compile(r"out_time_ms=(\d+)")
_PROGRESS_SPEED = re.compile(r"speed=\s*([\d.]+)x")
_PROGRESS_FPS = re.compile(r"fps=\s*([\d.]+)")

# progress callback gets {"fraction", "speed_x", "fps", "eta_seconds"}
ProgressCb = Callable[[dict], None]


@dataclass
class EncodeResult:
    mode: str
    output: Path
    ok: bool
    log_tail: str


def _vcodec_args(c: Compression) -> list[str]:
    lib = "libx265" if c.vcodec == "x265" else "libx264"
    args = ["-c:v", lib, "-preset", c.preset, "-crf", str(c.crf), "-pix_fmt", "yuv420p"]
    if c.tune:
        args += ["-tune", c.tune]
    if lib == "libx265":
        args += ["-tag:v", "hvc1"]
    return args


def _scale_filter(c: Compression) -> str:
    w, h = c.width, c.height
    if c.fit == "pad":
        return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1")
    if c.fit == "keep":
        return f"scale={w}:{h}:force_original_aspect_ratio=decrease,setsar=1"
    return f"scale={w}:{h},setsar=1"  # fill


def _ff_arg_escape(s: str) -> str:
    """Escape a value used inside a filtergraph option (e.g. subtitles=<here>)."""
    s = s.replace("\\", "\\\\").replace("'", r"\'")
    for ch in (":", "[", "]", ",", ";", "="):
        s = s.replace(ch, "\\" + ch)
    return s


@contextlib.contextmanager
def burnin_safe_source(src: Path) -> Iterator[tuple[Path, str]]:
    """Yield (cwd, filter_filename) that ffmpeg's subtitles filter can consume.

    Prefer a hardlink with a plain ASCII name next to the source (instant, no copy)
    so filtergraph escaping never bites. Fall back to escaping the real name.
    """
    src = Path(src)
    link = src.with_name(f".cps_burnin_{os.getpid()}{src.suffix}")
    try:
        os.link(src, link)
        yield src.parent, link.name
        return
    except OSError:
        pass
    finally:
        with contextlib.suppress(OSError):
            if link.exists():
                link.unlink()
    yield src.parent, _ff_arg_escape(src.name)


def _run(cmd: list[str], duration: float, cwd: Path | None,
         on_progress: ProgressCb | None,
         should_stop: Callable[[], bool] | None = None) -> tuple[int, str]:
    proc = subprocess.Popen(
        cmd, cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        **no_window_kwargs(),
    )
    tail: list[str] = []
    speed = 0.0
    fps = 0.0
    assert proc.stdout is not None
    for line in proc.stdout:
        if should_stop is not None and should_stop():
            # a Cancel button that leaves ffmpeg running is not a Cancel button
            proc.kill()
            break
        tail.append(line)
        if len(tail) > 40:
            tail.pop(0)

        m = _PROGRESS_SPEED.search(line)
        if m:
            speed = float(m.group(1))
        m = _PROGRESS_FPS.search(line)
        if m:
            fps = float(m.group(1))

        m = _PROGRESS_TIME.search(line)
        if m and duration > 0 and on_progress:
            # ffmpeg's out_time_ms is really microseconds
            secs = int(m.group(1)) / 1_000_000
            frac = min(1.0, secs / duration)
            eta = (duration - secs) / speed if speed > 0 and frac < 1.0 else 0.0
            on_progress({"fraction": frac, "speed_x": speed, "fps": fps,
                         "eta_seconds": eta})
    proc.wait()
    return proc.returncode, "".join(tail)


def build_soft_cmd(src: Path, out: Path, c: Compression, probe: Probe,
                   audio: Stream | None, sub: Stream | None,
                   limit_seconds: float | None = None) -> list[str]:
    exe = ffmpeg_setup.ffmpeg_path()
    cmd = [str(exe), "-y", "-hide_banner", "-nostdin", "-i", str(src),
           "-map", "0:v:0"]
    if audio is not None:
        cmd += ["-map", f"0:a:{audio.type_index}"]
    if sub is not None:
        cmd += ["-map", f"0:s:{sub.type_index}", "-map", "0:t?"]
    cmd += ["-vf", _scale_filter(c)]
    cmd += _vcodec_args(c)
    cmd += ["-c:a", c.acodec, "-b:a", c.abitrate, "-ac", str(c.achannels)]
    if sub is not None:
        cmd += ["-c:s", "copy", "-metadata:s:s:0", f"language={c.sub_lang}",
                "-disposition:s:0", "default"]
    if audio is not None:
        cmd += ["-metadata:s:a:0", f"language={audio.language or 'und'}",
                "-disposition:a:0", "default"]
    if limit_seconds:
        cmd += ["-t", str(limit_seconds)]
    cmd += ["-progress", "pipe:1", str(out)]
    return cmd


def build_burnin_cmd(cwd_name: str, out: Path, c: Compression, probe: Probe,
                     audio: Stream | None, sub_si: int,
                     limit_seconds: float | None = None) -> list[str]:
    exe = ffmpeg_setup.ffmpeg_path()
    cmd = [str(exe), "-y", "-hide_banner", "-nostdin", "-i", cwd_name,
           "-map", "0:v:0"]
    if audio is not None:
        cmd += ["-map", f"0:a:{audio.type_index}"]
    vf = f"{_scale_filter(c)},subtitles={cwd_name}:si={sub_si}"
    cmd += ["-vf", vf]
    cmd += _vcodec_args(c)
    cmd += ["-c:a", c.acodec, "-b:a", c.abitrate, "-ac", str(c.achannels)]
    if audio is not None:
        cmd += ["-metadata:s:a:0", f"language={audio.language or 'und'}"]
    if limit_seconds:
        cmd += ["-t", str(limit_seconds)]
    cmd += ["-movflags", "+faststart", "-progress", "pipe:1", str(out)]
    return cmd


def _progress_span(probe: Probe, limit_seconds: float | None) -> float:
    """How much video will actually be written — what progress is measured against."""
    if limit_seconds:
        return min(probe.duration, limit_seconds) or limit_seconds
    return probe.duration


def encode_soft(src: Path, out_dir: Path, title: str, c: Compression, probe: Probe,
                on_progress: ProgressCb | None = None,
                should_stop: Callable[[], bool] | None = None,
                limit_seconds: float | None = None) -> EncodeResult:
    audio = probe.choose_audio(c)
    sub = probe.choose_subtitle(c) if c.sub_mode in ("soft", "both") else None
    out = out_dir / f"{title}.{c.container_soft}"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_soft_cmd(src, out, c, probe, audio, sub, limit_seconds)
    rc, tail = _run(cmd, _progress_span(probe, limit_seconds), None, on_progress,
                    should_stop)
    return EncodeResult("soft", out, rc == 0 and out.is_file() and out.stat().st_size > 0, tail)


def encode_burnin(src: Path, out_dir: Path, title: str, c: Compression, probe: Probe,
                  on_progress: ProgressCb | None = None,
                  should_stop: Callable[[], bool] | None = None,
                  limit_seconds: float | None = None) -> EncodeResult:
    audio = probe.choose_audio(c)
    sub = probe.choose_subtitle(c)
    si = sub.type_index if sub is not None else 0
    out = out_dir / f"{title} [burned-in subs].mp4"
    out_dir.mkdir(parents=True, exist_ok=True)
    with burnin_safe_source(src) as (cwd, fname):
        cmd = build_burnin_cmd(fname, out, c, probe, audio, si, limit_seconds)
        rc, tail = _run(cmd, _progress_span(probe, limit_seconds), cwd, on_progress,
                        should_stop)
    return EncodeResult("burn-in", out, rc == 0 and out.is_file() and out.stat().st_size > 0, tail)


def outputs_for(mode: str, out_dir: Path, title: str, c: Compression) -> list[Path]:
    res = []
    if mode in ("soft", "both"):
        res.append(out_dir / f"{title}.{c.container_soft}")
    if mode in ("burn-in", "both"):
        res.append(out_dir / f"{title} [burned-in subs].mp4")
    return res
