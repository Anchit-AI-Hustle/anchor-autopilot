"""Timed lyrics: sheet alignment, line grouping, the ASS file and the lyric video itself."""
from anchor import lyrics as L


def _words(text, start=10.0, step=0.4):
    return [(w, start + i * step, start + i * step + 0.3) for i, w in enumerate(text.split())]


def test_sheet_words_take_the_sung_timing_and_tags_are_dropped():
    heard = _words("rain on the pigment concrete cold")                 # the model misheard "pavement"
    out = L.snap_to_sheet(heard, "[Verse 1]\nRain on the pavement\nConcrete cold")
    assert [w for w, _s, _e in out] == ["Rain", "on", "the", "pavement", "Concrete", "cold"]
    assert out[0][1] == heard[0][1] and out[-1][1] == heard[-1][1]       # matched words keep their time
    assert out[2][1] < out[3][1] < out[4][1]                              # the misheard one sits between its neighbours
    starts = [s for _w, s, _e in out]
    assert starts == sorted(starts)


def test_a_sheet_that_does_not_match_the_take_is_ignored():
    heard = _words("completely different words were actually sung here today")
    assert L.snap_to_sheet(heard, "nothing alike at all in this sheet of text") == heard


def test_lines_break_at_pauses_and_width_and_never_overlap():
    words = _words("we break the cage lost in the sound", 5.0) + _words("rain on the pavement concrete cold", 20.0)
    lines = L.to_lines(words, max_chars=18)
    assert all(sum(len(w[0]) + 1 for w in ln["words"]) <= 19 for ln in lines)
    assert any(ln["start"] >= 20.0 for ln in lines) and not any(ln["start"] < 20 < ln["end"] for ln in lines)
    for a, b in zip(lines, lines[1:]):
        assert a["end"] <= b["start"]


def test_no_models_means_no_lyrics_and_never_an_error(tmp_path, monkeypatch):
    mp3 = tmp_path / "a.mp3"
    mp3.write_bytes(b"x")
    assert L.timed_lines(mp3, tmp_path) == []                             # ANCHOR_LYRICS=0 from conftest
    monkeypatch.setenv("ANCHOR_LYRICS", "1")
    monkeypatch.setattr(L, "timed_lines", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no model")))
    assert L.lines_for(mp3, tmp_path / "w") == []
