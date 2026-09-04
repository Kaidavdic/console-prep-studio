from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressDialog, QPushButton, QSizePolicy, QSpinBox,
    QVBoxLayout, QWidget,
)

from ..core import ffmpeg_setup
from .common import plain_error
from .style import faint_css, muted_css
from .theme import C
from .widgets import Disclosure
from .worker import SampleWorker, retire_on_finish
from ..core.profiles import FIT_MODES, SUB_MODES

_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
            "medium", "slow", "slower", "veryslow"]
_TUNES = ["", "animation", "film", "grain", "stillimage", "fastdecode"]

# The two numbers that actually decide how a conversion looks and how long it
# takes, behind three names anyone can choose between. Everything else stays
# available under Advanced for whoever wants it.
_QUALITY = {
    "Smaller files": (26, "veryfast"),
    "Balanced": (21, "faster"),
    "Best picture": (18, "slow"),
}
_CUSTOM = "Custom"

# SUB_MODES in the order profiles defines them: both, burn-in, soft, none
_SUB_LABELS = {
    "both": "Make both versions (safest)",
    "burn-in": "Always on — part of the picture",
    "soft": "Can be turned on and off",
    "none": "No subtitles",
}
_FIT_LABELS = {
    "fill": "Stretch to fill the screen",
    "pad": "Add black bars",
    "keep": "Leave the shape alone",
}


class CompressionTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._loading = False
        self._sample: SampleWorker | None = None

        self.width = QSpinBox(); self.width.setRange(16, 3840); self.width.setSingleStep(16)
        self.height = QSpinBox(); self.height.setRange(16, 2160); self.height.setSingleStep(16)
        self.fit = QComboBox()
        for value in FIT_MODES:
            self.fit.addItem(_FIT_LABELS.get(value, value), value)
        self.vcodec = QComboBox(); self.vcodec.addItems(["x264", "x265"])
        self.crf = QSpinBox(); self.crf.setRange(0, 51)
        self.preset = QComboBox(); self.preset.addItems(_PRESETS)
        self.tune = QComboBox(); self.tune.addItems(_TUNES)
        self.quality = QComboBox(); self.quality.addItems([*_QUALITY, _CUSTOM])

        self.alang = QLineEdit(); self.alang.setPlaceholderText("jpn, und, eng")
        self.acodec = QComboBox(); self.acodec.addItems(["aac", "libopus", "ac3", "mp3"])
        self.abitrate = QLineEdit(); self.abitrate.setPlaceholderText("128k")
        self.achannels = QSpinBox(); self.achannels.setRange(1, 6)

        self.sub_mode = QComboBox()
        for value in SUB_MODES:
            self.sub_mode.addItem(_SUB_LABELS.get(value, value), value)
        self.sub_lang = QLineEdit(); self.sub_lang.setPlaceholderText("eng")
        self.sub_index = QSpinBox(); self.sub_index.setRange(-1, 30)
        self.sub_index.setSpecialValueText("by language")
        self.container = QComboBox(); self.container.addItems(["mkv", "mp4"])

        # a form of full-width inputs reads as a wall; size each to its content.
        # Minimums rather than fixed widths, so nothing clips when the OS is set
        # to a larger font size.
        for w, width in ((self.width, 90), (self.height, 90), (self.fit, 200),
                         (self.vcodec, 140), (self.crf, 90), (self.preset, 160),
                         (self.tune, 160), (self.acodec, 140), (self.abitrate, 110),
                         (self.achannels, 90), (self.sub_mode, 260),
                         (self.sub_lang, 110), (self.sub_index, 140),
                         (self.container, 110), (self.quality, 200)):
            w.setMinimumWidth(width)
            w.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.alang.setMinimumWidth(280)
        self.alang.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        # --- picture: one choice out front, the encoder knobs folded away ---
        vbox = QGroupBox("Picture")
        vf = QFormLayout(); vf.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        vf.addRow("Quality", self.quality)
        vf.addRow("", self._note(
            "Better quality means bigger files and a longer wait."))

        adv_v = Disclosure("Advanced picture settings")
        avf = QFormLayout(); avf.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        res = QHBoxLayout(); res.addWidget(self.width); res.addWidget(QLabel("x")); res.addWidget(self.height)
        res.addWidget(self.fit); res.addStretch(1)
        avf.addRow("Screen size", self._wrap(res))
        avf.addRow("Video format", self.vcodec)
        avf.addRow("Quality number (lower is better)", self.crf)
        avf.addRow("Encoding speed", self.preset)
        avf.addRow("Tuned for", self.tune)
        adv_v.add_layout(avf)

        vlay = QVBoxLayout(vbox)
        vlay.addLayout(vf)
        vlay.addWidget(adv_v)

        # --- sound ---
        abox = QGroupBox("Sound")
        af = QFormLayout(); af.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        af.addRow("Preferred language", self.alang)
        af.addRow("", self._note(
            "Three-letter codes, best first — for example “jpn, eng”."))

        adv_a = Disclosure("Advanced sound settings")
        aaf = QFormLayout(); aaf.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        aaf.addRow("Sound format", self.acodec)
        aaf.addRow("Sound quality", self.abitrate)
        aaf.addRow("Speakers", self.achannels)
        adv_a.add_layout(aaf)

        alay = QVBoxLayout(abox)
        alay.addLayout(af)
        alay.addWidget(adv_a)

        # --- subtitles ---
        sbox = QGroupBox("Subtitles")
        sf = QFormLayout(); sf.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        sf.addRow("Subtitles", self.sub_mode)
        sf.addRow("Language", self.sub_lang)

        adv_s = Disclosure("Advanced subtitle settings")
        asf = QFormLayout(); asf.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        asf.addRow("Which subtitle track", self.sub_index)
        asf.addRow("File type for switchable subtitles", self.container)
        adv_s.add_layout(asf)

        slay = QVBoxLayout(sbox)
        slay.addLayout(sf)
        slay.addWidget(adv_s)

        # --- pick tracks off a real episode instead of guessing indexes ---
        tbox = QGroupBox("Which tracks to use")
        tf = QFormLayout(tbox); tf.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.tpl_btn = QPushButton("Choose from an episode…")
        self.tpl_btn.clicked.connect(self._pick_tracks)
        self.tpl_clear = QPushButton("Back to automatic")
        self.tpl_clear.clicked.connect(self._clear_tracks)
        self.audio_pick = QLabel()
        self.sub_pick = QLabel()
        tpl_row = QHBoxLayout()
        tpl_row.addWidget(self.tpl_btn)
        tpl_row.addWidget(self.tpl_clear)
        tpl_row.addStretch(1)
        tf.addRow("Audio track", self.audio_pick)
        tf.addRow("Subtitle track", self.sub_pick)
        tf.addRow("", self._wrap(tpl_row))

        self.save_btn = QPushButton("Save these settings")
        self.save_btn.clicked.connect(self._save)
        self.ff_btn = QPushButton("Get the video tool")
        self.ff_btn.clicked.connect(self._locate_ffmpeg)
        self.test_btn = QPushButton("Try it on one video…")
        self.test_btn.clicked.connect(self._test)
        self.ff_label = QLabel()

        btnrow = QHBoxLayout()
        btnrow.addWidget(self.save_btn)
        btnrow.addWidget(self.test_btn)
        btnrow.addStretch(1)
        btnrow.addWidget(self.ff_btn)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(muted_css())

        lay = QVBoxLayout(self)
        lay.addWidget(self.hint)
        lay.addWidget(vbox)
        lay.addWidget(abox)
        lay.addWidget(sbox)
        lay.addWidget(tbox)
        lay.addLayout(btnrow)
        lay.addWidget(self.ff_label)
        lay.addStretch(1)

        for w in (self.width, self.height, self.crf, self.achannels, self.sub_index):
            w.valueChanged.connect(self._push)
        for w in (self.fit, self.vcodec, self.preset, self.tune, self.acodec,
                  self.sub_mode, self.container):
            w.currentIndexChanged.connect(self._push)
        for w in (self.alang, self.abitrate, self.sub_lang):
            w.editingFinished.connect(self._push)
        self.quality.currentTextChanged.connect(self._quality_picked)

        self.main.currentProfileChanged.connect(lambda _pid: self.load())
        self.main.profilesChanged.connect(self.load)
        self.load()
        self._refresh_ff_label()
        self._refresh_picks()

    # ---------------------------------------------------------------
    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget(); w.setLayout(layout); return w

    @staticmethod
    def _note(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(faint_css())
        return lbl

    # -- quality: the two numbers that matter, under three plain names ---
    def _quality_picked(self, name: str) -> None:
        if self._loading or name == _CUSTOM:
            return
        crf, preset = _QUALITY[name]
        self.crf.setValue(crf)
        self.preset.setCurrentText(preset)      # each fires _push on its own

    def _sync_quality(self) -> None:
        """Show which named quality the current numbers match, if any."""
        current = (self.crf.value(), self.preset.currentText())
        name = next((n for n, v in _QUALITY.items() if v == current), _CUSTOM)
        was_loading, self._loading = self._loading, True
        self.quality.setCurrentText(name)
        self._loading = was_loading

    def load(self) -> None:
        self._loading = True
        profile = self.main.current_profile()
        c = profile.compression
        self.width.setValue(c.width); self.height.setValue(c.height)
        self._select_data(self.fit, c.fit)
        self.vcodec.setCurrentText(c.vcodec)
        self.crf.setValue(c.crf)
        self.preset.setCurrentText(c.preset)
        self.tune.setCurrentText(c.tune or "")
        self.alang.setText(", ".join(c.audio_lang_priority))
        self.acodec.setCurrentText(c.acodec)
        self.abitrate.setText(c.abitrate)
        self.achannels.setValue(c.achannels)
        self._select_data(self.sub_mode, c.sub_mode)
        self.sub_lang.setText(c.sub_lang)
        self.sub_index.setValue(-1 if c.sub_index is None else c.sub_index)
        self.container.setCurrentText(c.container_soft)
        self.hint.setText(
            f"These settings are used when you convert for {profile.name}. "
            "Changes apply to the next conversion; “Save these settings” keeps "
            "them for next time.")
        self._loading = False
        self._sync_quality()
        if hasattr(self, 'audio_pick'):
            self._refresh_picks()

    @staticmethod
    def _select_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _push(self) -> None:
        if self._loading:
            return
        c = self.main.current_profile().compression
        c.width = self.width.value(); c.height = self.height.value()
        c.fit = self.fit.currentData()
        c.vcodec = self.vcodec.currentText()
        c.crf = self.crf.value()
        c.preset = self.preset.currentText()
        c.tune = self.tune.currentText()
        c.audio_lang_priority = [s.strip() for s in self.alang.text().split(",") if s.strip()] or ["und"]
        c.acodec = self.acodec.currentText()
        c.abitrate = self.abitrate.text().strip() or "128k"
        c.achannels = self.achannels.value()
        c.sub_mode = self.sub_mode.currentData()
        c.sub_lang = self.sub_lang.text().strip() or "eng"
        c.sub_index = None if self.sub_index.value() < 0 else self.sub_index.value()
        c.container_soft = self.container.currentText()
        self._sync_quality()

    # -- track template ------------------------------------------------
    def _refresh_picks(self) -> None:
        c = self.main.current_profile().compression
        self.audio_pick.setText(c.audio_choice.describe())
        self.sub_pick.setText(c.sub_choice.describe())
        self.tpl_clear.setEnabled(c.audio_choice.pinned or c.sub_choice.pinned)

        # a pinned track overrides these fields, so don't leave them looking
        # editable — two visible sources of truth is how people get confused
        why = "A specific track is pinned under “Which tracks to use”, so this is ignored."
        self.alang.setEnabled(not c.audio_choice.pinned)
        self.alang.setToolTip(why if c.audio_choice.pinned else "")
        for w in (self.sub_lang, self.sub_index):
            w.setEnabled(not c.sub_choice.pinned)
            w.setToolTip(why if c.sub_choice.pinned else "")

    def _pick_tracks(self) -> None:
        if not ffmpeg_setup.is_ready():
            QMessageBox.information(
                self, "The video tool is needed",
                "Press “Get the video tool” first — reading the languages inside "
                "a video needs it.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose one episode to read its languages from", "",
            "Video (*.mkv *.mp4 *.avi *.m4v *.mov *.ts)")
        if not path:
            return
        from ..core import ffprobe
        try:
            pr = ffprobe.probe(path)
        except Exception as e:  # noqa: BLE001
            self.main.log(f"could not read {path}: {e}")
            QMessageBox.warning(self, "Could not read that file",
                                "This file is damaged, or it is not a video.")
            return

        from .track_dialog import TrackTemplateDialog
        c = self.main.current_profile().compression
        dlg = TrackTemplateDialog(pr, c, self)
        if dlg.exec() != QDialog.Accepted:
            return
        c.audio_choice = dlg.audio_choice()
        c.sub_choice = dlg.sub_choice()
        self._refresh_picks()
        self.main.log(f"tracks from {Path(path).name} — "
                      f"audio: {c.audio_choice.describe()}, "
                      f"subtitles: {c.sub_choice.describe()}")

    def _clear_tracks(self) -> None:
        from ..core.profiles import TrackChoice
        c = self.main.current_profile().compression
        c.audio_choice = TrackChoice()
        c.sub_choice = TrackChoice()
        self._refresh_picks()

    def _save(self) -> None:
        self._push()
        self.main.persist_profiles()
        QMessageBox.information(
            self, "Saved",
            f"These settings are now the ones used for "
            f"{self.main.current_profile().name}.")

    def _refresh_ff_label(self) -> None:
        try:
            path = ffmpeg_setup.ffmpeg_path()
            self.ff_label.setText("The video tool is installed and ready.")
            self.ff_label.setStyleSheet(faint_css())
            self.ff_label.setToolTip(str(path))      # the path, for whoever wants it
        except ffmpeg_setup.FfmpegMissing:
            self.ff_label.setText(
                "The video tool is missing — press “Get the video tool”.")
            self.ff_label.setStyleSheet(f"color: {C.error};")
            self.ff_label.setToolTip("")

    def _locate_ffmpeg(self) -> None:
        from .ffmpeg_dialog import ensure_ffmpeg
        ensure_ffmpeg(self)
        self._refresh_ff_label()

    def _test(self) -> None:
        """Convert one minute of a real file so the settings can be judged.

        This runs on a worker thread: a minute of video takes tens of seconds to
        encode, and doing it in the click handler froze the whole window long
        enough for Windows to call it "Not Responding".
        """
        self._push()
        if not ffmpeg_setup.is_ready():
            QMessageBox.information(
                self, "The video tool is needed",
                "Press “Get the video tool” first — converting video needs it.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a video to try the settings on",
            "", "Video (*.mkv *.mp4 *.avi *.m4v *.mov *.ts)")
        if not path:
            return

        from ..core import settings
        out_dir = settings.data_dir() / "sample"
        self.main.log(f"test encode -> {out_dir}")

        self._sample = SampleWorker(Path(path), out_dir,
                                    self.main.current_profile().compression,
                                    parent=self)
        dlg = QProgressDialog("Converting a one-minute sample…", "Cancel", 0, 100, self)
        dlg.setWindowTitle("Trying your settings")
        dlg.setMinimumDuration(0)
        dlg.setValue(0)

        self._sample.progress.connect(lambda f: dlg.setValue(int(f * 100)))
        self._sample.done.connect(lambda ok, detail: self._test_done(dlg, ok, detail))
        dlg.canceled.connect(self._sample.request_stop)
        retire_on_finish(self._sample, lambda: setattr(self, "_sample", None))
        self._sample.start()

    def _test_done(self, dlg: QProgressDialog, ok: bool, detail: str) -> None:
        dlg.reset()
        if ok:
            QMessageBox.information(self, "Here is how it came out", detail)
        elif detail:
            QMessageBox.warning(self, "That did not work", plain_error(detail))
