from cps.core.episode_detect import build_episode_list, detect_number


def test_dragon_ball_som_names():
    paths = [
        "Dragon.Ball.001.V2.480p.DBox.DVD.REGRADE.Dual-Audio.FLAC2.0.x264-SoM.mkv",
        "Dragon.Ball.002.V2.480p.DBox.DVD.REGRADE.Dual-Audio.FLAC2.0.x264-SoM.mkv",
        "Dragon.Ball.010.V2.480p.DBox.DVD.REGRADE.Dual-Audio.FLAC2.0.x264-SoM.mkv",
    ]
    eps = build_episode_list(paths)
    assert [e.number for e in eps] == [1, 2, 10]
    assert eps[0].title == "Dragon Ball 001"
    assert eps[2].title == "Dragon Ball 010"


def test_sxxeyy():
    n, s = detect_number("Some.Show.S02E07.1080p.WEB.x265")
    assert (n, s) == (2007, 2)


def test_nnxmm():
    n, _ = detect_number("Some Show 1x07 720p")
    assert n == 1007


def test_anime_dash_number():
    n, _ = detect_number("[Group] Cool Anime - 07 [1080p][AAC]")
    assert n == 7


def test_bracket_number():
    n, _ = detect_number("Cool Anime [12] (BD 1080p)")
    assert n == 12


def test_movie_fallback_keeps_order_and_titles():
    paths = ["The Big Movie (2009) 1080p BluRay x264.mkv"]
    eps = build_episode_list(paths)
    assert eps[0].number is None
    assert "Big Movie" in eps[0].title


def test_resolution_not_mistaken_for_episode():
    n, _ = detect_number("Show.Name.1080p.x264")
    assert n != 1080
