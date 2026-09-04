"""End-to-end self-test — no external torrent or network needed.

Builds a 3-episode local torrent, seeds it in-process, then runs the real
pipeline against it and checks:

  * files download one at a time (only ~one raw episode on disk at a peak)
  * each episode is converted to both flavours, named/ordered correctly
  * the source is deleted after each convert
  * a second run resumes cleanly from the cached .torrent + fastresume
  * the localdir transfer backend delivers + md5-verifies the batch

Requires: ffmpeg on PATH, the package installed (`pip install -e .`), free
localhost UDP/TCP ports 6905-6907.

    python scripts/selftest.py [work_dir]
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "selftest_work").resolve()
if ROOT.exists():
    shutil.rmtree(ROOT)
(ROOT / "appdata").mkdir(parents=True)
os.environ["APPDATA"] = str(ROOT / "appdata")          # isolate config/state

import libtorrent as lt  # noqa: E402

from cps.core.pipeline import JobConfig, Pipeline  # noqa: E402
from cps.core.profiles import Compression, Profile, Transfer  # noqa: E402
from cps.core.sender import send_batch  # noqa: E402
from cps.core.torrent_engine import TorrentEngine  # noqa: E402

CONTENT = ROOT / "seedsrc" / "Cool Anime"
DL, OUT = ROOT / "dl", ROOT / "out"
CONTENT.mkdir(parents=True)


def make_ep(path: Path, n: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    srt = path.with_suffix(".srt")
    srt.write_text(f"1\n00:00:00,000 --> 00:00:03,000\nEpisode {n}\n", "utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=6:size=352x240:rate=12",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=6",
         "-i", str(srt), "-map", "0:v", "-map", "1:a", "-map", "2:s",
         "-metadata:s:a:0", "language=jpn", "-metadata:s:s:0", "language=eng",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-c:s", "srt", str(path)],
        check=True,
    )
    srt.unlink()


print("building sample episodes...")
for i in (1, 2, 3):
    make_ep(CONTENT / f"Cool.Anime.{i:03d}.720p.WEB.x264-GRP.mkv", i)
make_ep(CONTENT / "Extras" / "Cool.Anime.NCOP.mkv", 99)      # junk the user won't pick
(CONTENT / "readme.txt").write_text("not a video", "utf-8")

fs = lt.file_storage()
lt.add_files(fs, str(CONTENT))
ct = lt.create_torrent(fs, piece_size=32 * 1024)
ct.add_tracker("udp://127.0.0.1:6999/announce")
lt.set_piece_hashes(ct, str(CONTENT.parent))
tfile = ROOT / "cool.torrent"
tfile.write_bytes(lt.bencode(ct.generate()))

seed = lt.session({"listen_interfaces": "127.0.0.1:6905", "enable_dht": False,
                   "enable_lsd": True, "enable_natpmp": False, "enable_upnp": False})
satp = lt.add_torrent_params()
satp.ti = lt.torrent_info(str(tfile))
satp.save_path = str(CONTENT.parent)
satp.flags |= lt.torrent_flags.seed_mode
seed.add_torrent(satp)
time.sleep(1)

profile = Profile(
    id="test", name="Test", verify="md5",
    compression=Compression(width=320, height=240, preset="ultrafast", tune="",
                            crf=30, abitrate="96k", sub_mode="both", sub_index=0),
    transfer=Transfer(kind="localdir", local_path=str(ROOT / "device")),
)
# --- inspect the file list first (what the Download tab shows), then pick ep 1 + 3 ---
from cps.core.metadata import fetch_file_list  # noqa: E402

listed = fetch_file_list(str(tfile), timeout=15)
print("file list:", [(f.path.split("\\")[-1], f.is_video, f.episode) for f in listed])
pick = [f.path for f in listed if f.episode in ("Cool Anime 001", "Cool Anime 003")]

cfg = JobConfig(source=str(tfile), save_path=DL, output_root=OUT, profile=profile,
                delete_source=True, metadata_timeout=30, selected_files=pick)

peak_bytes = 0
events: list = []


ep2_bytes = 0


def probe_disk() -> None:
    global peak_bytes, ep2_bytes
    if not DL.exists():
        return
    seen = {}
    for f in DL.rglob("*.mkv"):
        st = f.stat()
        seen[(st.st_dev, st.st_ino)] = st.st_size      # dedupe the burn-in hardlink
        if "002" in f.name:
            ep2_bytes = max(ep2_bytes, st.st_size)
    peak_bytes = max(peak_bytes, sum(seen.values()))


def on_event(kind: str, payload: dict) -> None:
    events.append((kind, payload))
    if kind == "log":
        print("  ", payload["msg"])
    probe_disk()


engine = TorrentEngine(port=6906)
engine.session.apply_settings({"enable_lsd": True, "enable_dht": False})
pl = Pipeline(cfg, engine, on_event, lambda: False)
th = threading.Thread(target=pl.run)
th.start()
while th.is_alive():
    if pl.torrent:
        pl.torrent.connect_peer("127.0.0.1", 6905)
    probe_disk()
    time.sleep(0.2)
th.join()
engine.shutdown()

print("\nresume run...")
eng2 = TorrentEngine(port=6907)
ev2: list = []
Pipeline(cfg, eng2, lambda k, p: ev2.append((k, p)), lambda: False).run()
eng2.shutdown()

sent = send_batch(profile, OUT / "Test", lambda k, p: None, lambda: False)

# --- GUI regression: the app used to die the moment a job finished ---------
# The job state now says both episodes are done and the .torrent is cached, so
# the pipeline reaches "finished" almost immediately - which is exactly the code
# path that used to free a running QThread and abort the process.
print("\nGUI survival check...")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cps.app import MainWindow  # noqa: E402
from cps.ui.worker import PipelineWorker, retire_on_finish  # noqa: E402

qapp = QApplication([])
win = MainWindow()
win.show()
tab = win.download_tab

state = {"finished": None, "released": False, "finished_on_release": None}
gui_worker = PipelineWorker(cfg, port=6908, parent=tab)


def _released():
    state["released"] = True
    state["finished_on_release"] = gui_worker.isFinished()


gui_worker.finished_job.connect(lambda p: state.__setitem__("finished", p))
gui_worker.log.connect(win.log)
gui_worker.job_progress.connect(tab._job_progress)
retire_on_finish(gui_worker, _released)
gui_worker.start()

loop = QEventLoop()
tick = QTimer()
tick.setInterval(20)
tick.timeout.connect(lambda: state["released"] and loop.quit())
tick.start()
QTimer.singleShot(60000, loop.quit)
loop.exec()
tick.stop()

gui_alive = win.isVisible() and QApplication.instance() is not None
print(f" job finished: {bool(state['finished'])}   window still up: {gui_alive}")
win.close()

outs = sorted(p.name for p in OUT.rglob("*") if p.suffix in (".mkv", ".mp4"))
left = sorted(p.name for p in DL.rglob("*.mkv") if not p.name.startswith(".cps_"))
fin = next(p for k, p in reversed(events) if k == "finished")
fin2 = next(p for k, p in reversed(ev2) if k == "finished")

checks = {
    "file list = 5 real files, pads hidden": len(listed) == 5 and sum(f.is_video for f in listed) == 4,
    "only selected episodes produced": outs == [
        "Cool Anime 001 [burned-in subs].mp4", "Cool Anime 001.mkv",
        "Cool Anime 003 [burned-in subs].mp4", "Cool Anime 003.mkv"],
    "unselected episode 002 never downloaded": ep2_bytes == 0,
    "sources deleted": left == [],
    "disk stayed small": peak_bytes <= 122880 * 2,
    "job finished ok": fin.get("ok") and fin.get("done") == 2,
    "resume ok": fin2.get("ok") and fin2.get("done") == 2,
    "send + verify ok": len(sent) == 4 and all(i.ok for i in sent),
    "app survives a finished job": gui_alive and state["finished"] is not None,
    "worker released only after run() ended": state["finished_on_release"] is True,
}
print()
for name, passed in checks.items():
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
print(f"\n  peak source bytes on disk: {peak_bytes}")
print("\nRESULT:", "PASS" if all(checks.values()) else "FAIL")
sys.exit(0 if all(checks.values()) else 1)
