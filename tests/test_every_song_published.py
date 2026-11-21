"""Every song is published (Anchit, 2026-11-21: "ensure all songs like Sky Belongs To Nobody etc
are published - why arent they added yet"): a slot whose takes were all held publishes the best
of them, and a song held before is made again in its own slot (artist/redo.json)."""
import json
from pathlib import Path

from anchor import pipeline
from anchor.config import load_profile

ROOT = Path(__file__).resolve().parent.parent


def take(attempt, fails, score=0.0, mastered=None):
    return {"attempt": attempt, "fails": fails, "score": score, "mastered": mastered}


def test_the_best_held_take_is_the_gate_held_one_with_the_highest_score():
    held = [take(0, ["dropout of 1.2s inside the track"]),
            take(1, ["song gate: drop too soft"], 61.0, {"m": 1}),
            take(2, ["song gate: drop too soft", "song gate: flat"], 74.0, {"m": 2}),
            take(3, ["sounds like released drop 2026-11-01 (envelope 0.97, spectral sequence 0.95)"], 90.0, {"m": 3})]
    assert pipeline.pick_best_held(held)["attempt"] == 2


def test_a_broken_or_copied_take_is_never_published():
    held = [take(0, ["too quiet / near silent (RMS -60 dBFS)"]),
            take(1, ["sings its production notes: verse"]),
            take(2, ["audio contains NaN/Inf"]),
            take(3, ["title sung wrong, not standard English: sky"], 80.0, {"m": 3})]
    assert pipeline.pick_best_held(held) is None
    assert pipeline.pick_best_held([]) is None


def test_without_a_mastered_take_the_one_with_fewest_fails_goes_out():
    held = [take(0, ["dropout of 1.2s inside the track", "no low end (kick/bass share 0.1)"]),
            take(1, ["dropout of 0.9s inside the track"])]
    assert pipeline.pick_best_held(held)["attempt"] == 1


def test_shipping_held_takes_is_on_unless_switched_off(monkeypatch):
    monkeypatch.delenv("ANCHOR_SHIP_BEST_HELD", raising=False)
    assert pipeline.ship_best_held()
    monkeypatch.setenv("ANCHOR_SHIP_BEST_HELD", "0")
    assert not pipeline.ship_best_held()


def test_held_songs_are_made_again_in_their_slots():
    profile = load_profile()
    redo = json.loads((ROOT / "artist" / "redo.json").read_text())
    titles = {}
    for day in redo:
        r = pipeline.redo_for(profile, day, [])
        assert r is not None, day
        assert r["lane"] in {l.id for l in profile.active_lanes}
        titles[day] = r["song"].title
    assert titles["2026-11-20-2"] == "Sky Belongs To Nobody"
    assert "Ribs Like Wings" in titles.values() and "Stop The Rewind" in titles.values()


def test_a_redo_song_already_out_is_not_made_twice(tmp_path):
    p = tmp_path / "redo.json"
    p.write_text(json.dumps({"2026-11-20-2": {"song": "sky-belongs-to-nobody", "lane": "hardtechrap"}}))
    profile = load_profile()
    assert pipeline.redo_for(profile, "2026-11-20-2", [{"title": "Sky Belongs To Nobody"}], p) is None
    assert pipeline.redo_for(profile, "2026-11-22", [], p) is None
    p.write_text(json.dumps({"2026-11-20-2": {"song": "sky-belongs-to-nobody", "lane": "rawbounce"}}))
    assert pipeline.redo_for(profile, "2026-11-20-2", [], p) is None, "a retired lane is never used"
