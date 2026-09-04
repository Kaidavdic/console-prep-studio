"""Turn a media filename into an ordering key and a clean display title.

The pipeline downloads/converts files in the order this module returns, and names
the outputs from the title it produces.

Detection order (first hit wins):
  1. an explicit per-profile regex override with a capture group for the number
  2. SxxEyy / SxxEyyEzz          -> season*1000 + episode
  3. NNxMM  (e.g. 1x07)          -> season*1000 + episode
  4. common anime tags: " - 07 ", "[07]", "EP07", "E07", "#07"
  5. a bare 1-4 digit run in the name
  6. nothing -> keep original order, title = filename stem

`natural_key` is used as a tiebreaker so that, e.g., "Movie 2" sorts before
"Movie 10" when no episode number is found.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePath

VIDEO_EXTS = {
    ".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".m2ts", ".webm", ".wmv", ".flv", ".ogv",
}

_SxxEyy = re.compile(r"[Ss](\d{1,2})[._ ]?[Ee](\d{1,3})")
_NNxMM = re.compile(r"(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)")
_ANIME_TAGS = re.compile(
    r"(?:(?<=[-\s])|^)(?:ep?\.?\s?|#)?\[?(\d{1,4})\]?(?=[-\s.\[\]]|$)",
    re.IGNORECASE,
)
_BARE = re.compile(r"(?<!\d)(\d{1,4})(?!\d)")

# noise that should never be treated as an episode number
_NOISE = re.compile(
    r"\(?\b(?:19|20)\d{2}\b\)?|"                       # a year in 1900-2099
    r"\b(?:\d{3,4}p|x26[45]|h\.?26[45]|hevc|avc|bluray|brrip|bdrip|web-?dl|webrip|"
    r"10bit|8bit|aac2?|flac2?|ac3|dts|ddp?5|5\.1|2\.0|v\d|dvd|bd|web|hdtv|dbox|"
    r"remux|reencode|regrade|dual-?audio|multi|repack|proper)\b",
    re.IGNORECASE,
)


@dataclass(order=True)
class Episode:
    sort_index: float = field(init=False)
    number: int | None
    title: str
    src_rel: str  # path relative to the torrent/source root
    season: int | None = None

    def __post_init__(self) -> None:
        self.sort_index = float(self.number) if self.number is not None else float("inf")


def natural_key(s: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _strip_noise(name: str) -> str:
    return _NOISE.sub(" ", name)


def detect_number(name: str, override: str | None = None) -> tuple[int | None, int | None]:
    """Return (ordering_number, season) for a filename (no directory, no extension)."""
    if override:
        try:
            m = re.search(override, name)
        except re.error:
            m = None
        if m and m.groups():
            try:
                return int(m.group(1)), None
            except (ValueError, IndexError):
                pass

    m = _SxxEyy.search(name)
    if m:
        season, ep = int(m.group(1)), int(m.group(2))
        return season * 1000 + ep, season

    m = _NNxMM.search(name)
    if m:
        season, ep = int(m.group(1)), int(m.group(2))
        return season * 1000 + ep, season

    cleaned = _strip_noise(name)
    m = _ANIME_TAGS.search(cleaned)
    if m:
        return int(m.group(1)), None

    m = _BARE.search(cleaned)
    if m:
        return int(m.group(1)), None

    return None, None


def clean_title(series: str, ep: Episode) -> str:
    """Human name for the output file, e.g. 'Dragon Ball 007' or 'Some Movie'."""
    series = series.strip(" .-_")
    if ep.number is None:
        return _titlecase_stub(PurePath(ep.src_rel).stem)
    if ep.season is not None and ep.number >= 1000:
        e = ep.number - ep.season * 1000
        return f"{series} S{ep.season:02d}E{e:02d}" if series else f"S{ep.season:02d}E{e:02d}"
    n = f"{ep.number:03d}"
    return f"{series} {n}".strip()


def _titlecase_stub(stem: str) -> str:
    s = re.sub(r"[._]+", " ", stem)
    s = _strip_noise(s)
    s = re.sub(r"[\[(]\s*[\])]", " ", s)          # empty () or [] left by noise removal
    s = re.sub(r"[\[\]()]", " ", s)
    s = re.sub(r"[-\s]+$", "", re.sub(r"\s{2,}", " ", s)).strip(" .-_")
    return s or stem


def guess_series_name(rel_paths: list[str]) -> str:
    """Longest common human-looking prefix across the file names."""
    stems = [re.sub(r"[._]+", " ", PurePath(p).stem) for p in rel_paths]
    if not stems:
        return ""
    if len(stems) == 1:
        first = _strip_noise(stems[0])
        first = re.split(r"\bS\d{1,2}E\d{1,3}\b|\b\d{1,2}x\d{1,3}\b", first)[0]
        return re.sub(r"\s{2,}", " ", first).strip(" .-_0123456789")
    tokens = [s.split() for s in stems]
    common: list[str] = []
    for parts in zip(*tokens):
        if len(set(p.lower() for p in parts)) == 1 and not parts[0].isdigit():
            common.append(parts[0])
        else:
            break
    name = _strip_noise(" ".join(common))
    return re.sub(r"\s{2,}", " ", name).strip(" .-_")


def build_episode_list(rel_paths: list[str], regex_override: str | None = None) -> list[Episode]:
    """Map torrent file paths -> ordered Episode list (video files only)."""
    vids = [p for p in rel_paths if PurePath(p).suffix.lower() in VIDEO_EXTS]
    eps: list[Episode] = []
    for p in vids:
        stem = PurePath(p).stem
        number, season = detect_number(stem, regex_override)
        eps.append(Episode(number=number, title=stem, src_rel=p, season=season))

    series = guess_series_name([e.src_rel for e in eps])
    for e in eps:
        e.title = clean_title(series, e)

    eps.sort(key=lambda e: (e.sort_index, natural_key(e.src_rel)))
    return eps
