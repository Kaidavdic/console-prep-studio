import cps.core.settings as settings
from cps.core.pipeline import EpisodeState, JobState, job_key


def test_job_key_from_magnet_btih():
    m = "magnet:?xt=urn:btih:C12FE1C06BBA254A9DC9F519B335AA7C1367A88A&dn=x"
    assert job_key(m) == "c12fe1c06bba254a9dc9f519b335aa7c1367a88a"


def test_job_key_stable_for_path():
    a = job_key("D:/torrents/show.torrent")
    b = job_key("D:/torrents/show.torrent")
    assert a == b and len(a) == 40


def test_jobstate_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", lambda: tmp_path)
    (tmp_path / "state").mkdir()
    monkeypatch.setattr(settings, "state_dir", lambda: tmp_path / "state")

    js = JobState(key="abc", source="magnet:x", save_path="s", output_dir="o",
                  profile_id="knulli-rg35xxh", delete_source=True,
                  selected_files=["Show/ep01.mkv", "Show/ep03.mkv"],
                  episodes=[EpisodeState(src_rel="a.mkv", title="A 001", number=1, file_index=0)])
    js.episodes[0].status = "done"
    js.save()

    back = JobState.load("abc")
    assert back is not None
    assert back.episodes[0].status == "done"
    assert back.episodes[0].title == "A 001"
    assert back.delete_source is True
    assert back.selected_files == ["Show/ep01.mkv", "Show/ep03.mkv"]
