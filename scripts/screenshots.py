"""Render the README screenshots.

Builds the real window offscreen, fills each tab with representative data and
grabs a PNG. Repeatable, so the docs can be regenerated after any UI change:

    python scripts/screenshots.py [out_dir]
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

# the offscreen plugin has no font database on Windows, so text renders as
# empty boxes. Use the native platform there and just never show the window.
if sys.platform not in ("win32", "darwin"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_APP = Path(tempfile.mkdtemp(prefix="cps-shots-"))
os.environ["APPDATA"] = str(_APP)          # never touch the real config

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cps.app import MainWindow  # noqa: E402
from cps.ui.style import app_stylesheet  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots").resolve()
OUT.mkdir(parents=True, exist_ok=True)
SIZE = (1180, 820)


class FakeFile:
    """Stands in for metadata.TorrentFile."""
    __slots__ = ("index", "path", "size", "is_video", "episode", "number")

    def __init__(self, index, path, size, is_video=True, episode="", number=None):
        self.index = index
        self.path = path
        self.size = size
        self.is_video = is_video
        self.episode = episode
        self.number = number


GB = 1024 ** 3
TORRENT = [
    FakeFile(0, "Dragon Ball V2 480p DBox DVD/Dragon.Ball.001.V2.480p.mkv",
             int(3.4 * GB), True, "Dragon Ball 001", 1),
    FakeFile(2, "Dragon Ball V2 480p DBox DVD/Dragon.Ball.002.V2.480p.mkv",
             int(3.5 * GB), True, "Dragon Ball 002", 2),
    FakeFile(4, "Dragon Ball V2 480p DBox DVD/Dragon.Ball.003.V2.480p.mkv",
             int(3.3 * GB), True, "Dragon Ball 003", 3),
    FakeFile(6, "Dragon Ball V2 480p DBox DVD/Dragon.Ball.004.V2.480p.mkv",
             int(3.6 * GB), True, "Dragon Ball 004", 4),
    FakeFile(8, "Dragon Ball V2 480p DBox DVD/Dragon.Ball.005.V2.480p.mkv",
             int(3.4 * GB), True, "Dragon Ball 005", 5),
    FakeFile(10, "Dragon Ball V2 480p DBox DVD/Extras/Creditless Opening.mkv",
             int(0.4 * GB), True, "Dragon Ball Creditless Opening"),
    FakeFile(12, "Dragon Ball V2 480p DBox DVD/Extras/Creditless Ending.mkv",
             int(0.4 * GB), True, "Dragon Ball Creditless Ending"),
    FakeFile(14, "Dragon Ball V2 480p DBox DVD/Dragon.Ball.SoM.nfo", 4_200, False),
    FakeFile(16, "Dragon Ball V2 480p DBox DVD/readme.txt", 1_100, False),
]


def shot(widget, name: str) -> None:
    app.processEvents()
    path = OUT / f"{name}.png"
    widget.grab().save(str(path))
    print(f"  {path.name:26} {path.stat().st_size // 1024} KB")


app = QApplication([])
app.setStyleSheet(app_stylesheet())
win = MainWindow()
win.resize(*SIZE)
win.show()
app.processEvents()

tabs = win.centralWidget()
dl = win.download_tab

# --- 1. after Load files: pick what you want -------------------------------
dl.source.setText("magnet:?xt=urn:btih:4f6c2b9a1d3e5f708192a3b4c5d6e7f809a1b2c3&dn=Dragon+Ball")
dl._show_files(TORRENT)
# leave the two Extras unticked, as someone would
for row in (5, 6):
    dl.table.item(row, 0).setCheckState(Qt.Unchecked)
dl._update_selection_summary()
tabs.setCurrentWidget(dl)
shot(win, "01-choose-files")

# --- 2. mid-job: one converting, one downloading, three done ---------------
dl._set_running(True)
dl._plan([{"file_index": f.index, "number": f.number, "title": f.episode}
          for f in TORRENT[:5]])
for f in TORRENT[:3]:
    dl._update_episode({"file_index": f.index, "status": "done",
                        "title": f.episode, "error": ""})
dl._enc_progress({"file_index": 6, "mode": "burn-in", "fraction": 0.72,
                  "speed_x": 11.4, "eta_seconds": 96})
dl._dl_progress({"file_index": 8, "fraction": 0.41, "rate": 3_400_000,
                 "eta_seconds": 622, "peers": 14, "seeds": 3})
for f in TORRENT[5:]:
    dl._set_row(dl._row_for(f.index), 0.0, "skipped", "Not selected")
dl._job_progress({"episodes_done": 3, "episodes_total": 5,
                  "bytes_done": int(11.2 * GB), "bytes_total": int(17.2 * GB),
                  "fraction": 0.65, "rate": 3_400_000, "eta_seconds": 4_180})
dl.job_title.setText("Dragon Ball V2 480p DBox DVD")
shot(win, "02-running")

# --- 3. compression settings ----------------------------------------------
tabs.setCurrentWidget(win.compression_tab)
shot(win, "03-compression")

# --- 4. console profiles ---------------------------------------------------
tabs.setCurrentWidget(win.profiles_tab)
win.profiles_tab.list.setCurrentRow(0)
shot(win, "04-profiles")

# --- 5. send to the device -------------------------------------------------
staged = _APP / "output" / "RG35XX H - KNULLI"
staged.mkdir(parents=True, exist_ok=True)
for n in range(1, 6):
    for suffix, mb in ((".mkv", 171), (" [burned-in subs].mp4", 164)):
        f = staged / f"Dragon Ball {n:03d}{suffix}"
        with open(f, "wb") as fh:          # sparse: real size, no real bytes
            fh.truncate(mb * 1024 * 1024)

st = win.send_tab
st.folder.setText(str(staged))
st._scan()
st._sent_bytes = 3 * 171 * 1024 * 1024
st._batch_bytes = sum(p.stat().st_size for p in st._paths)
st._started = __import__("time").monotonic() - 240
for row in range(3):
    from cps.ui.progress_delegate import set_progress
    set_progress(st.table.item(row, 3), 1.0, "done", "Sent")
    st.table.item(row, 4).setText("verified")
set_progress(st.table.item(3, 3), 0.55, "sending", "Sending 55%")
st.title.setText("Sending to RG35XX H - KNULLI")
st._update_live(int(0.55 * 164 * 1024 * 1024))
tabs.setCurrentWidget(st)
shot(win, "05-send")

win.close()
shutil.rmtree(_APP, ignore_errors=True)
print(f"\nWrote {len(list(OUT.glob('*.png')))} screenshots to {OUT}")
