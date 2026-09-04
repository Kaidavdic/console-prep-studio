from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..core import ffmpeg_setup
from .style import muted_css
from ..core.profiles import FIT_MODES, SUB_MODES

_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
            "medium", "slow", "slower", "veryslow"]
_TUNES = ["", "animation", "film", "grain", "stillimage", "fastdecode"]


class CompressionTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._loading = False

        self.width = QSpinBox(); self.width.setRange(16, 3840); self.width.setSingleStep(16)
        self.height = QSpinBox(); self.height.setRange(16, 2160); self.height.setSingleStep(16)
        self.fit = QComboBox(); self.fit.addItems(FIT_MODES)
        self.vcodec = QComboBox(); self.vcodec.addItems(["x264", "x265"])
        self.crf = QSpinBox(); self.crf.setRange(0, 51)
        self.preset = QComboBox(); self.preset.addItems(_PRESETS)
        self.tune = QComboBox(); self.tune.addItems(_TUNES)

        self.alang = QLineEdit(); self.alang.setPlaceholderText("jpn, und, eng")
        self.acodec = QComboBox(); self.acodec.addItems(["aac", "libopus", "ac3", "mp3"])
        self.abitrate = QLineEdit(); self.abitrate.setPlaceholderText("128k")
        self.achannels = QSpinBox(); self.achannels.setRange(1, 6)

        self.sub_mode = QComboBox(); self.sub_mode.addItems(SUB_MODES)
        self.sub_lang = QLineEdit(); self.sub_lang.setPlaceholderText("eng")
        self.sub_index = QSpinBox(); self.sub_index.setRange(-1, 30)
        self.sub_index.setSpecialValueText("by language")
        self.container = QComboBox(); self.container.addItems(["mkv", "mp4"])

        # a form of full-width inputs reads as a wall; size each to its content
        for w, width in ((self.width, 90), (self.height, 90), (self.fit, 110),
                         (self.vcodec, 140), (self.crf, 90), (self.preset, 160),
                         (self.tune, 160), (self.acodec, 140), (self.abitrate, 110),
                         (self.achannels, 90), (self.sub_mode, 140),
                         (self.sub_lang, 110), (self.sub_index, 140),
                         (self.container, 110)):
            w.setFixedWidth(width)
        self.alang.setFixedWidth(280)

        vbox = QGroupBox("Video")
        vf = QFormLayout(vbox); vf.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        res = QHBoxLayout(); res.addWidget(self.width); res.addWidget(QLabel("x")); res.addWidget(self.height)
        res.addWidget(QLabel("fit")); res.addWidget(self.fit); res.addStretch(1)
        vf.addRow("Resolution", self._wrap(res))
        vf.addRow("Codec", self.vcodec)
        vf.addRow("CRF (lower = bigger/better)", self.crf)
        vf.addRow("Preset", self.preset)
        vf.addRow("Tune", self.tune)

        abox = QGroupBox("Audio")
        af = QFormLayout(abox); af.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        af.addRow("Language priority", self.alang)
        af.addRow("Codec", self.acodec)
        af.addRow("Bitrate", self.abitrate)
        af.addRow("Channels", self.achannels)

        sbox = QGroupBox("Subtitles")
        sf = QFormLayout(sbox); sf.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        sf.addRow("Mode", self.sub_mode)
        sf.addRow("Language", self.sub_lang)
        sf.addRow("Track index", self.sub_index)
        sf.addRow("Soft container", self.container)

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

        self.save_btn = QPushButton("Save to profile")
        self.save_btn.clicked.connect(self._save)
        self.ff_btn = QPushButton("Locate / download ffmpeg")
        self.ff_btn.clicked.connect(self._locate_ffmpeg)
        self.test_btn = QPushButton("Test on a file...")
        self.test_btn.clicked.connect(self._test)
        self.ff_label = QLabel()

        btnrow = QHBoxLayout()
        btnrow.addWidget(self.save_btn)
        btnrow.addWidget(self.test_btn)
        btnrow.addStretch(1)
        btnrow.addWidget(self.ff_btn)

        self.hint = QLabel("These settings belong to the device profile selected above. Edits take "
                           "effect on the next run; Save to profile makes them stick.")
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

        self.main.currentProfileChanged.connect(lambda _pid: self.load())
        self.main.profilesChanged.connect(self.load)
        self.load()
        self._refresh_ff_label()
        self._refresh_picks()

    # ---------------------------------------------------------------
    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget(); w.setLayout(layout); return w

    def load(self) -> None:
        self._loading = True
        c = self.main.current_profile().compression
        self.width.setValue(c.width); self.height.setValue(c.height)
        self.fit.setCurrentText(c.fit)
        self.vcodec.setCurrentText(c.vcodec)
        self.crf.setValue(c.crf)
        self.preset.setCurrentText(c.preset)
        self.tune.setCurrentText(c.tune or "")
        self.alang.setText(", ".join(c.audio_lang_priority))
        self.acodec.setCurrentText(c.acodec)
        self.abitrate.setText(c.abitrate)
        self.achannels.setValue(c.achannels)
        self.sub_mode.setCurrentText(c.sub_mode)
        self.sub_lang.setText(c.sub_lang)
        self.sub_index.setValue(-1 if c.sub_index is None else c.sub_index)
        self.container.setCurrentText(c.container_soft)
        self._loading = False
        if hasattr(self, 'audio_pick'):
            self._refresh_picks()

    def _push(self) -> None:
        if self._loading:
            return
        c = self.main.current_profile().compression
        c.width = self.width.value(); c.height = self.height.value()
        c.fit = self.fit.currentText()
        c.vcodec = self.vcodec.currentText()
        c.crf = self.crf.value()
        c.preset = self.preset.currentText()
        c.tune = self.tune.currentText()
        c.audio_lang_priority = [s.strip() for s in self.alang.text().split(",") if s.strip()] or ["und"]
        c.acodec = self.acodec.currentText()
        c.abitrate = self.abitrate.text().strip() or "128k"
        c.achannels = self.achannels.value()
        c.sub_mode = self.sub_mode.currentText()
        c.sub_lang = self.sub_lang.text().strip() or "eng"
        c.sub_index = None if self.sub_index.value() < 0 else self.sub_index.value()
        c.container_soft = self.container.currentText()

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
            QMessageBox.warning(self, "ffmpeg needed",
                                "Locate ffmpeg first — reading a file's tracks uses ffprobe.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open an episode to read its tracks", "",
            "Video (*.mkv *.mp4 *.avi *.m4v *.mov *.ts)")
        if not path:
            return
        from ..core import ffprobe
        try:
            pr = ffprobe.probe(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Could not read that file", str(e))
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
        QMessageBox.information(self, "Saved", "Compression settings saved to the profile.")

    def _refresh_ff_label(self) -> None:
        try:
            self.ff_label.setText(f"ffmpeg: {ffmpeg_setup.ffmpeg_path()}")
            self.ff_label.setStyleSheet("color: gray;")
        except ffmpeg_setup.FfmpegMissing:
            self.ff_label.setText("ffmpeg: not found — click 'Locate / download ffmpeg'")
            self.ff_label.setStyleSheet("color: #b00;")

    def _locate_ffmpeg(self) -> None:
        from .ffmpeg_dialog import ensure_ffmpeg
        ensure_ffmpeg(self)
        self._refresh_ff_label()

    def _test(self) -> None:
        self._push()
        if not ffmpeg_setup.is_ready():
            QMessageBox.warning(self, "ffmpeg", "Locate ffmpeg first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a video to test-encode a 60s sample",
            "", "Video (*.mkv *.mp4 *.avi *.m4v *.mov *.ts)")
        if not path:
            return
        from ..core import encoder, ffprobe, settings
        try:
            pr = ffprobe.probe(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "ffprobe", str(e))
            return
        pr.duration = min(pr.duration, 60.0) or 60.0
        c = self.main.current_profile().compression
        out_dir = settings.data_dir() / "sample"
        self.main.log(f"test encode -> {out_dir}")
        try:
            if c.sub_mode in ("soft", "both"):
                r = encoder.encode_soft(Path(path), out_dir, "SAMPLE", c, pr)
            else:
                r = encoder.encode_burnin(Path(path), out_dir, "SAMPLE", c, pr)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "encode failed", str(e))
            return
        msg = (f"{'OK' if r.ok else 'FAILED'} — {r.output.name}\n"
               f"{r.output.stat().st_size/1e6:.1f} MB for this sample\n\n{out_dir}")
        QMessageBox.information(self, "Test encode", msg)
