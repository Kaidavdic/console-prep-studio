"""Console profiles: everything needed to convert for, and deliver to, one device.

A profile bundles the compression defaults with the transfer settings so that
"prep for the RG35XX H" is a single pick. Profiles live in config.json under
"profiles"; the built-in KNULLI preset is always present and is re-seeded if the
user deletes it (they can still edit a clone).
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from . import settings

SUB_MODES = ("both", "burn-in", "soft", "none")
FIT_MODES = ("fill", "pad", "keep")           # fill = stretch to panel; pad = letterbox; keep = just scale
TRANSFER_KINDS = ("ssh", "smb", "localdir")
VERIFY_MODES = ("md5", "size", "none")


@dataclass
class TrackChoice:
    """A track picked on one episode, to be found again on all the others.

    Track order isn't guaranteed to be identical across a release, so pinning a
    bare index is fragile. Remember what the track *was* — its title, language
    and codec — and match on that first, falling back to the index only as a
    last resort. `mode="auto"` means fall back to the profile's language
    preference, which is the old behaviour.
    """
    mode: str = "auto"                 # auto | pinned
    language: str = ""
    title: str = ""
    codec: str = ""
    index: int = 0                     # index among tracks of this kind
    channels: int | None = None

    @property
    def pinned(self) -> bool:
        return self.mode == "pinned"

    def describe(self) -> str:
        if not self.pinned:
            return "chosen automatically by language"
        from .ffprobe import language_name
        detail = ", ".join(b for b in (language_name(self.language),
                                       self.codec.upper() if self.codec else "") if b)
        name = self.title or f"track {self.index + 1}"
        return f"{name} ({detail})" if detail else name


@dataclass
class Compression:
    width: int = 640
    height: int = 480
    fit: str = "fill"
    vcodec: str = "x264"                       # x264 | x265
    crf: int = 21
    preset: str = "faster"
    tune: str = "animation"                    # "" disables
    audio_lang_priority: list[str] = field(default_factory=lambda: ["jpn", "und", "eng"])
    acodec: str = "aac"
    abitrate: str = "128k"
    achannels: int = 2
    sub_mode: str = "both"                     # see SUB_MODES
    sub_lang: str = "eng"
    sub_index: int | None = 0                  # index among subtitle streams; None = by lang
    container_soft: str = "mkv"
    # tracks picked from a template episode; both default to automatic
    audio_choice: TrackChoice = field(default_factory=TrackChoice)
    sub_choice: TrackChoice = field(default_factory=TrackChoice)


@dataclass
class Transfer:
    kind: str = "ssh"                          # ssh | smb | localdir
    host: str = ""
    port: int = 22
    user: str = "root"
    remote_dir: str = ""
    # ssh auth: password kept in keyring under this ref; or a private key path
    password_ref: str = ""
    key_path: str = ""
    # smb
    share: str = ""
    # localdir
    local_path: str = ""
    post_hook: str = ""                        # shell run on device after copy (ssh only)


@dataclass
class Profile:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = "New profile"
    builtin: bool = False
    episode_regex: str = ""                    # optional override for episode_detect
    verify: str = "md5"
    compression: Compression = field(default_factory=Compression)
    transfer: Transfer = field(default_factory=Transfer)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Profile":
        d = copy.deepcopy(d)

        def _only(cls, src: dict) -> dict:
            fields = asdict(cls())
            return {**fields, **{k: v for k, v in src.items() if k in fields}}

        raw_comp = d.pop("compression", {})
        comp = Compression(**_only(Compression, raw_comp))
        # nested dataclasses come back as plain dicts from json
        for attr in ("audio_choice", "sub_choice"):
            val = getattr(comp, attr)
            if isinstance(val, dict):
                setattr(comp, attr, TrackChoice(**_only(TrackChoice, val)))
        tr = Transfer(**_only(Transfer, d.pop("transfer", {})))
        base = {k: d[k] for k in ("id", "name", "builtin", "episode_regex", "verify") if k in d}
        return Profile(compression=comp, transfer=tr, **base)


KNULLI_ID = "knulli-rg35xxh"


def knulli_preset() -> Profile:
    return Profile(
        id=KNULLI_ID,
        name="RG35XX H - KNULLI",
        builtin=True,
        verify="md5",
        compression=Compression(
            width=640, height=480, fit="fill",
            vcodec="x264", crf=21, preset="faster", tune="animation",
            audio_lang_priority=["jpn", "und", "eng"],
            acodec="aac", abitrate="128k", achannels=2,
            sub_mode="both", sub_lang="eng", sub_index=0,
        ),
        transfer=Transfer(
            kind="ssh", host="192.168.100.106", port=22, user="root",
            remote_dir="/userdata/roms/mpv",
            password_ref="knulli-rg35xxh",
            post_hook="curl -s -m 5 http://127.0.0.1:1234/reloadgames -o /dev/null "
                      "&& echo reloaded || echo 'reload failed - Update Gamelists manually'",
        ),
    )


def load_profiles() -> list[Profile]:
    cfg = settings.load_config()
    raw = cfg.get("profiles", [])
    profs = [Profile.from_dict(r) for r in raw]
    if not any(p.id == KNULLI_ID for p in profs):
        profs.insert(0, knulli_preset())
    return profs


def save_profiles(profs: list[Profile]) -> None:
    cfg = settings.load_config()
    cfg["profiles"] = [p.to_dict() for p in profs]
    settings.save_config(cfg)


def get_profile(pid: str) -> Profile | None:
    for p in load_profiles():
        if p.id == pid:
            return p
    return None
