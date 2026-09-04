"""Headless runner — the pipeline without the GUI. Handy for the fast PC over SSH,
for cron, and for testing.

    cps ffmpeg                              # download ffmpeg if missing
    cps profiles                            # list console profiles
    cps prep <magnet|file.torrent> [opts]   # download + convert episode by episode
    cps send  <folder> --profile <id>       # push a prepared folder to the device
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import ffmpeg_setup, sender, settings
from .core.pipeline import JobConfig, Pipeline
from .core.profiles import get_profile, load_profiles
from .core.torrent_engine import TorrentEngine


def _print_event(kind: str, payload: dict) -> None:
    if kind == "log":
        print(payload["msg"], flush=True)
    elif kind == "download_progress":
        print(f"\r  dl {payload['fraction']*100:5.1f}%  "
              f"{payload['rate']/1e6:5.2f} MB/s  {payload['peers']} peers   ",
              end="", flush=True)
        if payload["fraction"] >= 1.0:
            print()
    elif kind == "encode_progress":
        print(f"\r  {payload['mode']:8} {payload['fraction']*100:5.1f}%   ", end="", flush=True)
        if payload["fraction"] >= 1.0:
            print()
    elif kind in ("send_item_done",):
        mark = "OK " if payload["ok"] else "FAIL"
        print(f"  [{mark}] {payload['name']}  {payload['detail']}", flush=True)
    elif kind == "finished":
        print(f"\n== finished: {payload}", flush=True)


def cmd_ffmpeg(_args) -> int:
    if ffmpeg_setup.is_ready():
        print(f"ffmpeg: {ffmpeg_setup.ffmpeg_path()}")
        print(f"ffprobe: {ffmpeg_setup.ffprobe_path()}")
        return 0
    print("downloading ffmpeg...")
    ffmpeg_setup.download(lambda got, total: print(
        f"\r  {got/1e6:.1f}/{total/1e6:.1f} MB", end="", flush=True))
    print("\ndone:", ffmpeg_setup.ffmpeg_dir())
    return 0


def cmd_profiles(_args) -> int:
    for p in load_profiles():
        c = p.compression
        print(f"{p.id:20}  {p.name}")
        print(f"    video   {c.width}x{c.height} {c.vcodec} crf{c.crf} {p.compression.fit}")
        print(f"    audio   {c.audio_lang_priority} -> {c.acodec} {c.abitrate} {c.achannels}ch")
        print(f"    subs    {c.sub_mode} ({c.sub_lang})")
        print(f"    send    {p.transfer.kind} {p.transfer.host}:{p.transfer.port} "
              f"{p.transfer.remote_dir or p.transfer.local_path}")
    return 0


def cmd_prep(args) -> int:
    if not ffmpeg_setup.is_ready():
        print("ffmpeg missing — run `cps ffmpeg` first (or install ffmpeg).", file=sys.stderr)
        return 2
    profile = get_profile(args.profile)
    if not profile:
        print(f"no such profile: {args.profile}", file=sys.stderr)
        return 2
    save = Path(args.save or (settings.data_dir() / "downloads")).expanduser()
    out = Path(args.out or (settings.data_dir() / "output")).expanduser()
    cfg = JobConfig(
        source=args.source, save_path=save, output_root=out, profile=profile,
        delete_source=not args.keep_source,
        episode_limit=args.limit,
        metadata_timeout=args.metadata_timeout,
    )
    engine = TorrentEngine(port=args.port)
    stop = {"v": False}
    try:
        Pipeline(cfg, engine, _print_event, lambda: stop["v"]).run()
    except KeyboardInterrupt:
        stop["v"] = True
        print("\ninterrupted", file=sys.stderr)
        return 130
    finally:
        engine.shutdown()
    return 0


def cmd_convert(args) -> int:
    if not ffmpeg_setup.is_ready():
        print("ffmpeg missing — run `cps ffmpeg` first.", file=sys.stderr)
        return 2
    profile = get_profile(args.profile)
    if not profile:
        print(f"no such profile: {args.profile}", file=sys.stderr)
        return 2

    from .core.local_job import LocalJob, LocalJobConfig, find_videos

    files = find_videos(args.folder, not args.no_recursive)
    if args.match:
        import fnmatch
        files = [f for f in files if fnmatch.fnmatch(f.name.lower(), args.match.lower())]
    if not files:
        print(f"no video files found in {args.folder}", file=sys.stderr)
        return 1

    print(f"{len(files)} file(s):")
    for f in files:
        print(f"  {f.name}")
    if not args.yes:
        if input("convert these? [y/N] ").strip().lower() not in ("y", "yes"):
            return 0

    out = Path(args.out or (settings.default_output_dir())).expanduser()
    cfg = LocalJobConfig(files=files, output_root=out, profile=profile,
                         delete_source=args.delete_source,
                         rename_episodes=not args.keep_names)
    LocalJob(cfg, _print_event, lambda: False).run()
    return 0


def cmd_send(args) -> int:
    profile = get_profile(args.profile)
    if not profile:
        print(f"no such profile: {args.profile}", file=sys.stderr)
        return 2
    items = sender.send_batch(profile, args.folder, _print_event, lambda: False)
    return 0 if items and all(i.ok for i in items) else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cps", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ffmpeg", help="download ffmpeg if missing").set_defaults(func=cmd_ffmpeg)
    sub.add_parser("profiles", help="list console profiles").set_defaults(func=cmd_profiles)

    pr = sub.add_parser("prep", help="download + convert episode by episode")
    pr.add_argument("source", help="magnet: URI or path to a .torrent")
    pr.add_argument("--profile", default="knulli-rg35xxh")
    pr.add_argument("--save", help="where the torrent downloads (default: appdata/downloads)")
    pr.add_argument("--out", help="where converted files go (default: appdata/output)")
    pr.add_argument("--keep-source", action="store_true", help="don't delete each source after convert")
    pr.add_argument("--limit", type=int, default=None, help="only the first N episodes")
    pr.add_argument("--port", type=int, default=6881)
    pr.add_argument("--metadata-timeout", type=float, default=180.0)
    pr.set_defaults(func=cmd_prep)

    cv = sub.add_parser("convert", help="convert video files already on disk")
    cv.add_argument("folder")
    cv.add_argument("--profile", default="knulli-rg35xxh")
    cv.add_argument("--out", help="where converted files go")
    cv.add_argument("--match", help="only files matching this glob, e.g. '*S01*'")
    cv.add_argument("--no-recursive", action="store_true", help="skip subfolders")
    cv.add_argument("--keep-names", action="store_true",
                    help="don't rename outputs to the detected episode titles")
    cv.add_argument("--delete-source", action="store_true",
                    help="delete each source file after it converts")
    cv.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    cv.set_defaults(func=cmd_convert)

    sd = sub.add_parser("send", help="push a prepared folder to a device")
    sd.add_argument("folder")
    sd.add_argument("--profile", required=True)
    sd.set_defaults(func=cmd_send)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
