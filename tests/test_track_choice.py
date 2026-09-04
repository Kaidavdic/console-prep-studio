"""Picking a track on one episode must find the same track on the others,
even when the release doesn't order its streams identically."""
import pytest

from cps.core.ffprobe import Probe, Stream
from cps.core.profiles import Compression, TrackChoice


def _episode(audio, subs) -> Probe:
    p = Probe(path="ep.mkv", duration=1440.0)
    p.video = [Stream(0, 0, "h264", "jpn", "")]
    p.audio = [Stream(10 + i, i, c, lang, title, channels=ch)
               for i, (c, lang, title, ch) in enumerate(audio)]
    p.subtitles = [Stream(20 + i, i, c, lang, title)
                   for i, (c, lang, title) in enumerate(subs)]
    return p


TEMPLATE = _episode(
    audio=[("aac", "eng", "English Dub", 2),
           ("flac", "jpn", "1986 Mono Broadcast Audio", 1)],
    subs=[("ass", "eng", "Stylized Subtitles"),
          ("subrip", "eng", "Basic Subtitles")],
)


def _pin_from(probe, kind, index) -> TrackChoice:
    streams = getattr(probe, kind)
    s = streams[index]
    return TrackChoice(mode="pinned", language=s.language, title=s.title,
                       codec=s.codec, index=index, channels=s.channels)


def test_pinned_track_found_again_when_order_changes():
    comp = Compression(audio_choice=_pin_from(TEMPLATE, "audio", 1),
                       sub_choice=_pin_from(TEMPLATE, "subtitles", 0))
    # next episode has the Japanese track first instead of second
    other = _episode(
        audio=[("flac", "jpn", "1986 Mono Broadcast Audio", 1),
               ("aac", "eng", "English Dub", 2)],
        subs=[("subrip", "eng", "Basic Subtitles"),
              ("ass", "eng", "Stylized Subtitles")],
    )
    assert other.choose_audio(comp).title == "1986 Mono Broadcast Audio"
    assert other.choose_subtitle(comp).title == "Stylized Subtitles"


def test_falls_back_to_language_when_titles_are_missing():
    comp = Compression(audio_choice=_pin_from(TEMPLATE, "audio", 1))
    untitled = _episode(audio=[("aac", "eng", "", 2), ("flac", "jpn", "", 1)], subs=[])
    assert untitled.choose_audio(comp).language == "jpn"


def test_falls_back_to_index_when_nothing_matches():
    comp = Compression(audio_choice=_pin_from(TEMPLATE, "audio", 1))
    nothing = _episode(audio=[("aac", "und", "", 2), ("aac", "und", "", 6)], subs=[])
    assert nothing.choose_audio(comp).channels == 6      # index 1


def test_automatic_still_uses_language_priority():
    comp = Compression(audio_lang_priority=["jpn", "eng"])
    assert TEMPLATE.choose_audio(comp).language == "jpn"
    assert not comp.audio_choice.pinned


def test_choice_survives_a_profile_round_trip():
    from cps.core.profiles import Profile
    p = Profile(name="x")
    p.compression.audio_choice = _pin_from(TEMPLATE, "audio", 1)
    back = Profile.from_dict(p.to_dict())
    assert isinstance(back.compression.audio_choice, TrackChoice)
    assert back.compression.audio_choice.pinned
    assert back.compression.audio_choice.title == "1986 Mono Broadcast Audio"


def test_describe_is_human_readable():
    assert "automatic" in TrackChoice().describe()
    c = _pin_from(TEMPLATE, "audio", 1)
    # spells the language out rather than showing the raw ISO tag
    assert c.describe() == "1986 Mono Broadcast Audio (Japanese, FLAC)"


def test_describe_falls_back_to_a_track_number_when_untitled():
    c = TrackChoice(mode="pinned", language="eng", codec="ass", index=2)
    assert c.describe() == "track 3 (English, ASS)"


def test_describe_names_an_untagged_language():
    c = TrackChoice(mode="pinned", language="und", title="Commentary", codec="aac")
    assert c.describe() == "Commentary (no language tag, AAC)"
