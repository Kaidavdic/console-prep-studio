from pathlib import Path

import pytest

from cps.core import encoder
from cps.core.ffprobe import Probe, Stream
from cps.core.profiles import Compression


@pytest.fixture(autouse=True)
def fake_ffmpeg(monkeypatch):
    monkeypatch.setattr(encoder.ffmpeg_setup, "ffmpeg_path", lambda: Path("ffmpeg"))


def _probe():
    p = Probe(path="in.mkv", duration=1440.0)
    p.video = [Stream(0, 0, "h264", "jpn", "")]
    p.audio = [Stream(1, 0, "flac", "jpn", "1986 Mono", channels=1)]
    p.subtitles = [
        Stream(2, 0, "ass", "eng", "Stylized"),
        Stream(3, 1, "subrip", "eng", "Basic"),
    ]
    return p


def test_soft_cmd_maps_jpn_audio_and_default_sub():
    p = _probe()
    c = Compression(sub_mode="soft", sub_index=0)
    cmd = encoder.build_soft_cmd(Path("in.mkv"), Path("out.mkv"), c, p,
                                 p.pick_audio(c.audio_lang_priority),
                                 p.pick_subtitle(c.sub_lang, c.sub_index))
    assert "0:a:0" in cmd
    assert "0:s:0" in cmd
    assert "0:t?" in cmd
    assert "copy" in cmd                       # -c:s copy
    assert "scale=640:480,setsar=1" in cmd
    assert "+faststart" not in cmd             # mkv, no faststart
    assert cmd[cmd.index("-disposition:s:0") + 1] == "default"


def test_burnin_cmd_has_subtitles_filter_and_faststart():
    p = _probe()
    c = Compression(sub_mode="burn-in")
    cmd = encoder.build_burnin_cmd("in.mkv", Path("out.mp4"), c, p,
                                   p.pick_audio(c.audio_lang_priority), 0)
    vf = cmd[cmd.index("-vf") + 1]
    assert vf == "scale=640:480,setsar=1,subtitles=in.mkv:si=0"
    assert "+faststart" in cmd
    assert "libx264" in cmd


def test_x265_uses_libx265_and_hvc1_tag():
    p = _probe()
    c = Compression(vcodec="x265", sub_mode="soft")
    cmd = encoder.build_soft_cmd(Path("in.mkv"), Path("out.mkv"), c, p,
                                 p.pick_audio(c.audio_lang_priority), None)
    assert "libx265" in cmd
    assert "hvc1" in cmd


def test_pad_fit_builds_letterbox_filter():
    c = Compression(fit="pad")
    f = encoder._scale_filter(c)
    assert "force_original_aspect_ratio=decrease" in f and "pad=640:480" in f


def test_pick_audio_falls_back_when_language_absent():
    p = _probe()
    p.audio = [Stream(1, 0, "aac", "und", "")]
    assert p.pick_audio(["jpn"]).language == "und"


def test_outputs_for_both_mode():
    c = Compression()
    outs = encoder.outputs_for("both", Path("/o"), "Dragon Ball 001", c)
    assert [o.name for o in outs] == ["Dragon Ball 001.mkv", "Dragon Ball 001 [burned-in subs].mp4"]
