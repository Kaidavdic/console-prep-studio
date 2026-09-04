"""Thin ffprobe wrapper: read the stream layout of a media file."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import ffmpeg_setup
from .procutil import no_window_kwargs


@dataclass
class Stream:
    index: int              # absolute stream index in the file
    type_index: int         # index within its own kind (0-based): a:0, a:1, s:0 ...
    codec: str
    language: str           # ISO-ish tag from metadata, "und" if missing
    title: str
    channels: int | None = None
    width: int | None = None
    height: int | None = None
    disposition_default: bool = False


@dataclass
class Probe:
    path: str
    duration: float = 0.0
    video: list[Stream] = field(default_factory=list)
    audio: list[Stream] = field(default_factory=list)
    subtitles: list[Stream] = field(default_factory=list)
    has_attachments: bool = False

    def pick_audio(self, lang_priority: list[str]) -> Stream | None:
        for want in lang_priority:
            for s in self.audio:
                if s.language.lower().startswith(want.lower()):
                    return s
        return self.audio[0] if self.audio else None

    def pick_subtitle(self, lang: str | None, index: int | None) -> Stream | None:
        if not self.subtitles:
            return None
        if index is not None and 0 <= index < len(self.subtitles):
            return self.subtitles[index]
        if lang:
            for s in self.subtitles:
                if s.language.lower().startswith(lang.lower()):
                    return s
        return self.subtitles[0]


def _tag(d: dict, key: str, default: str = "") -> str:
    return (d.get("tags") or {}).get(key, default)


def probe(path: str | Path) -> Probe:
    exe = ffmpeg_setup.ffprobe_path()
    out = subprocess.run(
        [str(exe), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True, **no_window_kwargs(),
    )
    data = json.loads(out.stdout)
    p = Probe(path=str(path))
    try:
        p.duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
    except (TypeError, ValueError):
        p.duration = 0.0

    counters = {"video": 0, "audio": 0, "subtitle": 0, "attachment": 0}
    for st in data.get("streams", []):
        kind = st.get("codec_type", "")
        ti = counters.get(kind, 0)
        counters[kind] = ti + 1
        disp = st.get("disposition", {}) or {}
        s = Stream(
            index=st.get("index", 0),
            type_index=ti,
            codec=st.get("codec_name", "?"),
            language=_tag(st, "language", "und"),
            title=_tag(st, "title", ""),
            channels=st.get("channels"),
            width=st.get("width"),
            height=st.get("height"),
            disposition_default=bool(disp.get("default")),
        )
        if kind == "video" and not disp.get("attached_pic"):
            p.video.append(s)
        elif kind == "audio":
            p.audio.append(s)
        elif kind == "subtitle":
            p.subtitles.append(s)
        elif kind == "attachment":
            p.has_attachments = True
    return p
