"""Convert video files that are already on disk — no torrent involved.

Same conversion and the same progress events as the torrent pipeline, so the UI
can show both with one table. Use it for a folder you downloaded some other way,
or to re-encode a batch with different settings.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import encoder, ffprobe
from .episode_detect import VIDEO_EXTS, build_episode_list
from .pipeline import EpisodeState, _h
from .profiles import Profile

EventCb = Callable[[str, dict], None]
StopCb = Callable[[], bool]


def find_videos(folder: str | Path, recursive: bool = True) -> list[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        return []
    it = folder.rglob("*") if recursive else folder.glob("*")
    return sorted(p for p in it
                  if p.is_file() and p.suffix.lower() in VIDEO_EXTS
                  and not p.name.startswith(".cps_"))


@dataclass
class LocalJobConfig:
    files: list[Path]
    output_root: Path
    profile: Profile
    delete_source: bool = False          # off by default: these are the user's own files
    rename_episodes: bool = True         # use detected episode titles for output names


class LocalJob:
    """Mirrors Pipeline's event contract: episodes, episode_update,
    encode_progress, job_progress, finished."""

    def __init__(self, cfg: LocalJobConfig, on_event: EventCb, should_stop: StopCb):
        self.cfg = cfg
        self.emit = on_event
        self.should_stop = should_stop
        self.episodes: list[EpisodeState] = []
        self._enc_seconds = 0.0
        self._enc_count = 0

    def _log(self, msg: str) -> None:
        self.emit("log", {"msg": msg})

    def _out_dir(self) -> Path:
        import re
        safe = re.sub(r'[<>:"/\\|?*]', "_", self.cfg.profile.name).strip() or "output"
        return self.cfg.output_root / safe

    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001
            self._log(f"stopped: {e}")
            self.emit("finished", {"ok": False, "error": str(e)})

    def _run(self) -> None:
        files = [Path(f) for f in self.cfg.files if Path(f).is_file()]
        if not files:
            raise RuntimeError("None of the selected files are still there.")

        names = [f.name for f in files]
        detected = {e.src_rel: e for e in build_episode_list(names,
                                                            self.cfg.profile.episode_regex or None)}
        for i, f in enumerate(files):
            d = detected.get(f.name)
            title = (d.title if (d and self.cfg.rename_episodes) else f.stem)
            self.episodes.append(EpisodeState(
                src_rel=str(f), title=title,
                number=d.number if d else None, file_index=i))

        self.emit("episodes", {"episodes": [asdict(e) for e in self.episodes]})
        self._job_progress()
        self._log(f"converting {len(self.episodes)} file(s) into {self._out_dir()}")

        for ep in self.episodes:
            if self.should_stop():
                # the work already finished still counts — the screen says so
                self.emit("finished", {
                    "ok": False, "error": "stopped",
                    "done": sum(1 for e in self.episodes if e.status == "done"),
                    "total": len(self.episodes),
                    "output_dir": str(self._out_dir())})
                return
            self._convert(ep)

        done = sum(1 for e in self.episodes if e.status == "done")
        self.emit("finished", {"ok": True, "done": done, "total": len(self.episodes),
                               "output_dir": str(self._out_dir())})
        self._log(f"finished: {done} of {len(self.episodes)} converted")

    def _convert(self, ep: EpisodeState) -> None:
        src = Path(ep.src_rel)
        i = ep.file_index
        ep.status = "converting"
        self.emit("episode_update", asdict(ep))
        self._log(f"converting   {ep.title}  ({_h(src.stat().st_size)})")

        try:
            probe = ffprobe.probe(src)
        except Exception as e:  # noqa: BLE001
            self._fail(ep, f"could not read the file: {e}")
            return

        c = self.cfg.profile.compression
        out_dir = self._out_dir()
        started = time.monotonic()

        def cb(mode: str):
            def _cb(p: dict) -> None:
                self.emit("encode_progress", {"file_index": i, "mode": mode, **p})
            return _cb

        results = []
        try:
            if c.sub_mode in ("soft", "both"):
                results.append(encoder.encode_soft(src, out_dir, ep.title, c, probe,
                                                   cb("soft")))
            if c.sub_mode in ("burn-in", "both"):
                results.append(encoder.encode_burnin(src, out_dir, ep.title, c, probe,
                                                     cb("burn-in")))
        except Exception as e:  # noqa: BLE001
            self._fail(ep, f"ffmpeg crashed: {e}")
            return

        bad = [r for r in results if not r.ok]
        if bad or not results:
            for r in bad:
                self._log(r.log_tail)
            self._fail(ep, "; ".join(f"{r.mode} failed" for r in bad) or "nothing was produced")
            return

        self._enc_seconds += max(0.001, time.monotonic() - started)
        self._enc_count += 1
        ep.outputs = [str(r.output) for r in results]
        for r in results:
            self._log(f"  -> {r.output.name}  ({_h(r.output.stat().st_size)})")

        if self.cfg.delete_source:
            try:
                src.unlink()
                self._log(f"deleted {src.name}")
            except OSError as e:
                self._log(f"could not delete {src.name}: {e}")

        ep.status = "done"
        self.emit("episode_update", asdict(ep))
        self._job_progress()

    def _fail(self, ep: EpisodeState, why: str) -> None:
        ep.status = "error"
        ep.error = why
        self.emit("episode_update", asdict(ep))
        self._log(f"FAILED {ep.title}: {why}")
        self._job_progress()

    def _job_progress(self) -> None:
        done = sum(1 for e in self.episodes if e.status == "done")
        total = len(self.episodes)
        left = total - done
        avg = self._enc_seconds / self._enc_count if self._enc_count else 0.0
        self.emit("job_progress", {
            "episodes_done": done, "episodes_total": total,
            "bytes_done": 0, "bytes_total": 0,
            "fraction": (done / total) if total else 0.0,
            "rate": 0,
            "eta_seconds": avg * left,
        })
