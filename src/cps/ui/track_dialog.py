"""Pick the audio and subtitle track by looking at one real episode.

Choosing "subtitle stream 2" blind is guesswork. Open an episode you already
know is representative, see what is actually in it — "1986 Mono Broadcast Audio,
Japanese, FLAC, mono" — click the one you want, and that choice is matched
against every other episode by title and language rather than by position.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QVBoxLayout,
)

from ..core.ffprobe import Probe, Stream, language_name
from ..core.profiles import Compression, TrackChoice
from .style import muted_css

def describe_audio(s: Stream) -> str:
    bits = [language_name(s.language)]
    if s.channels == 1:
        bits.append("mono")
    elif s.channels == 2:
        bits.append("stereo")
    elif s.channels:
        bits.append(f"{s.channels} channels")
    bits.append(s.codec.upper())
    return ", ".join(bits)


def describe_sub(s: Stream) -> str:
    kind = {"ass": "styled", "ssa": "styled", "subrip": "plain text",
            "hdmv_pgs_subtitle": "image based", "dvd_subtitle": "image based"}
    bits = [language_name(s.language)]
    if s.codec in kind:
        bits.append(kind[s.codec])
    else:
        bits.append(s.codec.upper())
    return ", ".join(bits)


class TrackTemplateDialog(QDialog):
    """Shows one file's tracks and returns the two TrackChoices."""

    def __init__(self, probe: Probe, comp: Compression, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose tracks from this episode")
        self.resize(620, 560)
        self.probe = probe

        heading = QLabel(f"Tracks in {Path(probe.path).name}")
        f = heading.font()
        f.setWeight(QFont.DemiBold)
        heading.setFont(f)
        heading.setWordWrap(True)

        note = QLabel(
            "Whatever you pick here is matched on every other episode by its name "
            "and language, so it still works if the track order changes.")
        note.setWordWrap(True)
        note.setStyleSheet(muted_css())

        self.audio_list = QListWidget()
        self.sub_list = QListWidget()
        self._fill(self.audio_list, probe.audio, describe_audio, comp.audio_choice,
                   auto_text="Pick automatically by language "
                             f"({', '.join(comp.audio_lang_priority)})")
        self._fill(self.sub_list, probe.subtitles, describe_sub, comp.sub_choice,
                   auto_text=f"Pick automatically by language ({comp.sub_lang})")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(heading)
        lay.addWidget(note)
        lay.addWidget(self._section("Audio"))
        lay.addWidget(self.audio_list, 1)
        lay.addWidget(self._section("Subtitles"))
        lay.addWidget(self.sub_list, 1)
        lay.addWidget(buttons)

    @staticmethod
    def _section(text: str) -> QLabel:
        lbl = QLabel(text)
        f = lbl.font()
        f.setWeight(QFont.DemiBold)
        lbl.setFont(f)
        return lbl

    def _fill(self, widget: QListWidget, streams: list[Stream], describe,
              current: TrackChoice, auto_text: str) -> None:
        auto = QListWidgetItem(auto_text)
        auto.setData(Qt.UserRole, None)
        widget.addItem(auto)

        for i, s in enumerate(streams):
            label = s.title.strip() or f"Track {i + 1}"
            item = QListWidgetItem(f"{label}\n    {describe(s)}")
            item.setData(Qt.UserRole, i)
            if s.disposition_default:
                item.setToolTip("Marked as the default track in the file")
            widget.addItem(item)

        if not streams:
            empty = QListWidgetItem("This file has none")
            empty.setFlags(Qt.NoItemFlags)
            widget.addItem(empty)

        widget.setCurrentRow(self._preselect(streams, current))

    @staticmethod
    def _preselect(streams: list[Stream], current: TrackChoice) -> int:
        if not current.pinned:
            return 0
        for i, s in enumerate(streams):
            if current.title and s.title.strip().lower() == current.title.strip().lower():
                return i + 1
        if 0 <= current.index < len(streams):
            return current.index + 1
        return 0

    @staticmethod
    def _choice(widget: QListWidget, streams: list[Stream]) -> TrackChoice:
        item = widget.currentItem()
        idx = item.data(Qt.UserRole) if item else None
        if idx is None or not streams:
            return TrackChoice()                       # automatic
        s = streams[idx]
        return TrackChoice(mode="pinned", language=s.language, title=s.title.strip(),
                           codec=s.codec, index=idx, channels=s.channels)

    def audio_choice(self) -> TrackChoice:
        return self._choice(self.audio_list, self.probe.audio)

    def sub_choice(self) -> TrackChoice:
        return self._choice(self.sub_list, self.probe.subtitles)
