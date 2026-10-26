"""A song sings its lyrics, never its production notes (Anchit, 2026-10-26)."""
import pytest

from anchor import lyriccheck
from anchor.brief import make_brief
from anchor.config import load_profile
from anchor.music import structure

# what faster-whisper (small) heard on the released records, 2026-10-26
HEARD_TRANSMIT_PRESSURE = (
    "Close your eyes. Pressurizing bar-by-bar rap verse Compton flow on the beat Counted in eight bars then "
    "the roof flies Transmit pressure Hands up, hands up For eight to sixteen bars Sirens behind the hook "
    "alone over a health cord The room drops away A playful tease of the hook rap verse Layed back flow over "
    "the groove Lights going green in the crowd")
HEARD_ELASTIC_ORBIT = ("We fly tonight. So fully over 8 to 16 bars, Reverse Whisper echoes alone over a held chord. "
                       "The room drops away a playful tease of the hook. Follow the light.")


def test_the_released_records_that_sang_their_notes_are_caught():
    tp = lyriccheck.sung_notes(HEARD_TRANSMIT_PRESSURE, None)
    assert any("eight to sixteen bars" in n for n in tp) and any("playful tease of the hook" in n for n in tp)
    assert any("flow over the groove" in n for n in tp) and any("flow on the beat" in n for n in tp)
    eo = lyriccheck.sung_notes(HEARD_ELASTIC_ORBIT, None)
    assert any("eight to sixteen bars" in n for n in eo), "the recogniser writes numbers as digits"
    assert any("held chord the room drops away" in n for n in eo)


def test_a_song_that_sings_only_its_words_passes():
    heard = "Close your eyes. Counted in eight bars then the roof flies. Transmit pressure, hands up, hands up."
    assert lyriccheck.sung_notes(heard, None) == []
    # a written line may share words with a note: what was written is always allowed
    sheet = "[Verse]\nwe came for the drop and the room drops away\n\n[Drop]\nGO! GO!"
    assert lyriccheck.sung_notes("we came for the drop and the room drops away", sheet) == []


def test_no_sheet_carries_a_direction_any_more():
    """The cause: directions inside the tags. Every sheet the robot writes is bare tags + words."""
    p = load_profile()
    vocab = lyriccheck.note_vocabulary()
    for i in range(1, 29):
        b = make_brief(p, f"2026-11-{i:02d}", [])
        for line in b["lyrics"].splitlines():
            if line.startswith("["):
                assert " - " not in line and "," not in line and len(line) < 16, line
        sung = " ".join(lyriccheck.sung_lines(b["lyrics"]))
        assert lyriccheck.sung_notes(sung, None, vocab) == [], f"{b['id']}: a written line reads like a note"
    for seconds in (60, 150, 245):
        assert all(len(t) < 16 for t in structure(seconds).splitlines())


def test_the_check_is_off_in_tests_and_reports_when_it_cannot_listen(monkeypatch, tmp_path):
    assert not lyriccheck.enabled()
    monkeypatch.setattr(lyriccheck, "hear", lambda *a, **k: None)
    assert lyriccheck.check(tmp_path / "x.wav", "[Intro]\nhi") == {"heard": None, "notes": [], "checked": False}


@pytest.mark.slow
def test_a_take_that_sings_its_notes_is_made_again_and_never_shipped(fast_profile, site_dir, tmp_path, monkeypatch):
    from anchor import pipeline
    from anchor.music import FixtureEngine

    class Engine(FixtureEngine):           # a real engine's name, so the take is listened to
        name = "acestep_cpp"

    monkeypatch.setattr(pipeline, "get_engine", lambda *a, **k: Engine())
    monkeypatch.setattr(lyriccheck, "enabled", lambda: True)
    heard = iter([{"heard": "for eight to sixteen bars", "notes": ["for eight to sixteen bars"], "checked": True},
                  {"heard": "close your eyes", "notes": [], "checked": True}])
    monkeypatch.setattr(lyriccheck, "check", lambda *a, **k: next(heard))
    cat = site_dir / "data" / "catalog.json"
    meta = pipeline.make(fast_profile, "2026-11-02", tmp_path / "d", art_mode="procedural", catalog_path=cat,
                         queue_dir=tmp_path / "q", use_queue=False, retries=1)
    first = meta["qc"]["attempts"][0]
    assert not first["ok"] and any("sings its production notes" in f for f in first["fail"])
    assert meta["qc"]["attempts"][-1]["ok"]

    monkeypatch.setattr(lyriccheck, "check",
                        lambda *a, **k: {"heard": "rap verse", "notes": ["rap verse laid back flow"], "checked": True})
    with pytest.raises(pipeline.QualityError):
        pipeline.make(fast_profile, "2026-11-03", tmp_path / "e", art_mode="procedural", catalog_path=cat,
                      queue_dir=tmp_path / "q", use_queue=False, retries=1)


def test_a_song_rendered_before_the_check_is_held_unless_verified(tmp_path, monkeypatch):
    import json
    from anchor.__main__ import main
    old = tmp_path / "build" / "2026-10-26-3"
    old.mkdir(parents=True)
    (old / "meta.json").write_text(json.dumps({"brief": {"id": "2026-10-26-3"}, "qc": {"attempts": [{"attempt": 0}]}}))
    ok = tmp_path / "build" / "2026-10-26-4"
    ok.mkdir(parents=True)
    (ok / "meta.json").write_text(json.dumps({"brief": {"id": "2026-10-26-4"}, "qc": {"attempts": [{"attempt": 0}]}}))
    new = tmp_path / "build" / "2026-10-27"
    new.mkdir(parents=True)
    (new / "meta.json").write_text(json.dumps({"brief": {"id": "2026-10-27"}, "qc": {"attempts": [{"attempt": 0, "heard": "hi"}]}}))
    verified = tmp_path / "v.json"
    verified.write_text(json.dumps({"ids": ["2026-10-26-4"]}))
    assert lyriccheck.unchecked(old, verified) and not lyriccheck.unchecked(ok, verified)
    assert not lyriccheck.unchecked(new, verified), "a take made with the check is never held by this"
    assert not lyriccheck.unchecked(tmp_path / "build" / "none", verified), "no build: nothing to hold"
    # the publish loop asks has-drop; a held song reads as 'do not post'
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps({"drops": []}))
    monkeypatch.setattr("anchor.__main__.CATALOG_PATH", cat, raising=False)
    monkeypatch.setattr(lyriccheck, "VERIFIED", verified)
    monkeypatch.chdir(tmp_path)
    import io, contextlib
    for drop_id, want in (("2026-10-26-3", "yes"), ("2026-10-26-4", "no"), ("2026-10-27", "no")):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["has-drop", "--date", drop_id])
        assert out.getvalue().strip() == want, drop_id


def test_the_shipped_verified_list_holds_the_songs_that_sang_their_notes():
    import json
    v = json.loads(lyriccheck.VERIFIED.read_text())
    assert "2026-10-26-4" in v["ids"] and not set(v["held"]) & set(v["ids"])
