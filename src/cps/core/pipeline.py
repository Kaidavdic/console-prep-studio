"""The per-torrent state machine: download one episode, convert it, (optionally)
delete the source, persist progress, repeat. Resumable across app restarts.

Framework-agnostic: it reports progress through an `on_event` callback and checks
`should_stop()` between steps. The GUI runs `Pipeline.run()` on a worker thread.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import encoder, ffprobe, settings
from .episode_detect import build_episode_list
from .profiles import Profile
from .torrent_engine import Torrent, TorrentEngine

EventCb = Callable[[str, dict], None]
StopCb = Callable[[], bool]

_BTIH = re.compile(r"xt=urn:btih:([0-9a-zA-Z]+)", re.IGNORECASE)


def job_key(source: str) -> str:
    m = _BTIH.search(source)
    if m:
        return m.group(1).lower()[:40]
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:40]


@dataclass
class EpisodeState:
    src_rel: str
    title: str
    number: int | None
    file_index: int
    status: str = "queued"        # queued|downloading|converting|done|error|skipped
    outputs: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class JobState:
    key: str
    source: str
    save_path: str
    output_dir: str
    profile_id: str
    delete_source: bool
    series: str = ""
    selected_files: list[str] | None = None      # torrent-relative paths chosen by the user
    episodes: list[EpisodeState] = field(default_factory=list)
    resume_file: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)

    @property
    def path(self) -> Path:
        return settings.state_dir() / f"{self.key}.json"

    def save(self) -> None:
        self.updated = time.time()
        d = asdict(self)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, indent=2), "utf-8")
        tmp.replace(self.path)

    @staticmethod
    def load(key: str) -> "JobState | None":
        p = settings.state_dir() / f"{key}.json"
        if not p.exists():
            return None
        d = json.loads(p.read_text("utf-8"))
        eps = [EpisodeState(**e) for e in d.pop("episodes", [])]
        return JobState(episodes=eps, **d)


@dataclass
class JobConfig:
    source: str
    save_path: Path
    output_root: Path
    profile: Profile
    delete_source: bool = True
    metadata_timeout: float = 180.0
    episode_limit: int | None = None          # only process the first N episodes
    selected_files: list[str] | None = None   # torrent-relative paths; None = every video file


class Pipeline:
    def __init__(self, cfg: JobConfig, engine: TorrentEngine,
                 on_event: EventCb, should_stop: StopCb):
        self.cfg = cfg
        self.engine = engine
        self.emit = on_event
        self.should_stop = should_stop
        self.state: JobState | None = None
        self.torrent: Torrent | None = None
        # running stats, used for speed + ETA
        self._rate = 0.0              # smoothed download rate, bytes/s
        self._dl_bytes = 0            # bytes downloaded so far this run
        self._dl_seconds = 0.0
        self._enc_seconds = 0.0       # time spent encoding so far this run
        self._enc_count = 0
        self._sizes_cache: dict[int, int] | None = None

    # -- helpers ------------------------------------------------------
    def _log(self, msg: str) -> None:
        self.emit("log", {"msg": msg})

    def _emit_job_progress(self, current_done: int = 0, current_total: int = 0) -> None:
        """Whole-job totals + a best-effort ETA for everything that's left."""
        if not self.state:
            return
        eps = self.state.episodes
        todo = [e for e in eps if e.status not in ("done", "skipped", "error")]
        done = sum(1 for e in eps if e.status == "done")

        sizes = self._episode_sizes()
        total_bytes = sum(sizes.get(e.file_index, 0) for e in eps
                          if e.status not in ("skipped", "error"))
        done_bytes = sum(sizes.get(e.file_index, 0) for e in eps if e.status == "done")
        done_bytes += current_done

        remaining_bytes = max(0, total_bytes - done_bytes)
        dl_eta = remaining_bytes / self._rate if self._rate > 1 else 0.0
        avg_enc = self._enc_seconds / self._enc_count if self._enc_count else 0.0
        enc_eta = avg_enc * max(0, len(todo) - (1 if current_total else 0))

        self.emit("job_progress", {
            "episodes_done": done, "episodes_total": len(eps),
            "bytes_done": done_bytes, "bytes_total": total_bytes,
            "fraction": (done_bytes / total_bytes) if total_bytes else 0.0,
            "rate": self._rate,
            "eta_seconds": dl_eta + enc_eta,
        })

    def _episode_sizes(self) -> dict[int, int]:
        if not self.torrent:
            return {}
        if getattr(self, "_sizes_cache", None) is None:
            files = self.torrent.files()
            self._sizes_cache = {i: s for i, (_p, s) in enumerate(files)}
        return self._sizes_cache

    def _persist_resume(self) -> None:
        if not self.torrent or not self.state:
            return
        buf = self.torrent.save_resume()
        if buf:
            rf = settings.state_dir() / f"{self.state.key}.fastresume"
            rf.write_bytes(buf)
            self.state.resume_file = str(rf)
            self.state.save()

    def _out_dir(self) -> Path:
        safe = re.sub(r'[<>:"/\\|?*]', "_", self.cfg.profile.name).strip() or "output"
        return self.cfg.output_root / safe

    # -- main -------------------------------------------------------
    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 - report, don't crash the thread
            self._log(f"FATAL: {e}")
            self.emit("finished", {"ok": False, "error": str(e)})

    def _run(self) -> None:
        key = job_key(self.cfg.source)
        state = JobState.load(key)
        resume_buf = None
        if state:
            self._log(f"resuming job {key}")
            rf = Path(state.resume_file) if state.resume_file else None
            if rf and rf.exists():
                resume_buf = rf.read_bytes()
        else:
            state = JobState(
                key=key, source=self.cfg.source, save_path=str(self.cfg.save_path),
                output_dir=str(self._out_dir()), profile_id=self.cfg.profile.id,
                delete_source=self.cfg.delete_source,
                selected_files=self.cfg.selected_files,
            )
        self.state = state

        ti_cache = settings.state_dir() / f"{key}.torrent"

        self.emit("phase", {"phase": "metadata"})
        self._log("adding torrent / fetching metadata...")
        self.torrent = self.engine.add(
            self.cfg.source, self.cfg.save_path, resume_buf,
            ti_path=ti_cache if ti_cache.exists() else None)
        self.torrent.wait_metadata(self.cfg.metadata_timeout)
        files = self.torrent.files()
        self._log(f"metadata ready: {len(files)} files")
        if not ti_cache.exists():
            try:
                ti_cache.write_bytes(self.torrent.torrent_file_buf())
            except Exception:  # noqa: BLE001
                pass

        if not state.episodes:
            rel_paths = [p for p, _ in files]
            wanted = state.selected_files or self.cfg.selected_files
            if wanted:
                wanted_set = set(wanted)
                rel_paths = [p for p in rel_paths if p in wanted_set]
                self._log(f"user selected {len(rel_paths)} of {len(files)} files")
            eps = build_episode_list(rel_paths, self.cfg.profile.episode_regex or None)
            index_of = {p: i for i, (p, _) in enumerate(files)}
            state.episodes = [
                EpisodeState(src_rel=e.src_rel, title=e.title, number=e.number,
                             file_index=index_of[e.src_rel])
                for e in eps
            ]
            if not state.episodes:
                raise RuntimeError("no video files found in this torrent")
            state.save()

        self.torrent.deselect_all()
        self.emit("episodes", {"episodes": [asdict(e) for e in state.episodes]})
        self._emit_job_progress()

        todo = [e for e in state.episodes if e.status not in ("done", "skipped")]
        if self.cfg.episode_limit is not None:
            allowed = {id(e) for e in state.episodes[: self.cfg.episode_limit]}
            todo = [e for e in todo if id(e) in allowed]

        for ep in todo:
            if self.should_stop():
                self._log("stop requested — saving progress")
                self._persist_resume()
                self.emit("finished", {"ok": False, "error": "stopped"})
                return
            self._process_episode(ep)

        self._persist_resume()
        done = sum(1 for e in state.episodes if e.status == "done")
        self.emit("finished", {"ok": True, "done": done, "total": len(state.episodes),
                               "output_dir": str(self._out_dir())})
        self._log(f"job complete: {done}/{len(state.episodes)} episodes ready in {self._out_dir()}")

    # -- one episode ------------------------------------------------
    def _process_episode(self, ep: EpisodeState) -> None:
        assert self.torrent and self.state
        i = ep.file_index
        src_abs = Path(self.cfg.save_path) / ep.src_rel
        _, size = self.torrent.files()[i]

        self._space_check(size)

        # --- download ---
        ep.status = "downloading"
        ep.error = ""
        self.state.save()
        self.emit("episode_update", asdict(ep))
        self._log(f"downloading  {ep.title}  ({_h(size)})")
        self.torrent.select_only(i)

        last = 0.0
        started = time.monotonic()
        while not self.torrent.file_done(i):
            if self.should_stop():
                return
            self.engine.pump()
            got = self.torrent.file_bytes(i)
            frac = self.torrent.file_fraction(i)
            st = self.torrent.status()
            self._rate = _ema(self._rate, st["download_rate"])
            now = time.monotonic()
            if now - last > 0.5:
                self.emit("download_progress", {
                    "file_index": i, "fraction": frac,
                    "downloaded": got, "total": size,
                    "rate": st["download_rate"], "avg_rate": self._rate,
                    "eta_seconds": (size - got) / self._rate if self._rate > 1 else 0.0,
                    "peers": st["num_peers"], "seeds": st["num_seeds"],
                })
                self._emit_job_progress(current_done=got, current_total=size)
                last = now
            time.sleep(0.5)

        self._dl_bytes += size
        self._dl_seconds += max(0.001, time.monotonic() - started)
        self._log(f"downloaded   {ep.title}")
        self.emit("download_progress", {
            "file_index": i, "fraction": 1.0, "downloaded": size, "total": size,
            "rate": 0, "avg_rate": self._rate, "eta_seconds": 0.0, "peers": 0, "seeds": 0})
        self._persist_resume()

        # --- convert ---
        ep.status = "converting"
        self.state.save()
        self.emit("episode_update", asdict(ep))
        c = self.cfg.profile.compression
        try:
            probe = ffprobe.probe(src_abs)
        except Exception as e:  # noqa: BLE001
            ep.status = "error"
            ep.error = f"ffprobe failed: {e}"
            self.state.save()
            self.emit("episode_update", asdict(ep))
            self._log(f"ERROR {ep.title}: {ep.error}")
            return

        out_dir = self._out_dir()
        results = []
        enc_started = time.monotonic()

        def enc_cb(mode: str):
            def _cb(p: dict) -> None:
                self.emit("encode_progress", {"file_index": i, "mode": mode, **p})
                self._emit_job_progress()
            return _cb

        try:
            if c.sub_mode in ("soft", "both"):
                self._log(f"encoding     {ep.title}  [soft subs]")
                results.append(encoder.encode_soft(
                    src_abs, out_dir, ep.title, c, probe, enc_cb("soft")))
            if c.sub_mode in ("burn-in", "both"):
                self._log(f"encoding     {ep.title}  [burned-in subs]")
                results.append(encoder.encode_burnin(
                    src_abs, out_dir, ep.title, c, probe, enc_cb("burn-in")))
        except Exception as e:  # noqa: BLE001
            ep.status = "error"
            ep.error = f"encode crashed: {e}"
            self.state.save()
            self.emit("episode_update", asdict(ep))
            self._log(f"ERROR {ep.title}: {ep.error}")
            return

        bad = [r for r in results if not r.ok]
        if bad or not results:
            ep.status = "error"
            ep.error = "; ".join(f"{r.mode}: ffmpeg failed" for r in bad) or "no output produced"
            for r in bad:
                self._log(r.log_tail)
            self.state.save()
            self.emit("episode_update", asdict(ep))
            self._log(f"ERROR {ep.title}: {ep.error}")
            return

        self._enc_seconds += max(0.001, time.monotonic() - enc_started)
        self._enc_count += 1

        ep.outputs = [str(r.output) for r in results]
        for r in results:
            self._log(f"  -> {r.output.name}  ({_h(r.output.stat().st_size)})")

        # --- delete source ---
        if self.cfg.delete_source:
            try:
                src_abs.unlink()
                self._log(f"deleted source {ep.src_rel}")
            except OSError as e:
                self._log(f"could not delete source ({e}) — leaving it")
            # keep priority at 0; never force a re-check

        ep.status = "done"
        self.state.save()
        self.emit("episode_update", asdict(ep))
        self._emit_job_progress()

    def _space_check(self, need_bytes: int) -> None:
        for target in ({self.cfg.save_path, self._out_dir().parent}):
            try:
                free = shutil.disk_usage(target).free
            except OSError:
                continue
            required = need_bytes + max(need_bytes // 4, 300 * 1024 * 1024)
            if free < required:
                raise RuntimeError(
                    f"not enough free space on {target}: need ~{_h(required)}, have {_h(free)}"
                )


def _ema(prev: float, sample: float, alpha: float = 0.3) -> float:
    """Smooth a noisy rate so the ETA doesn't jump around."""
    if sample <= 0:
        return prev
    return sample if prev <= 0 else prev * (1 - alpha) + sample * alpha


def _h(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.1f} {unit}"
        f /= 1024
    return f"{n} B"
