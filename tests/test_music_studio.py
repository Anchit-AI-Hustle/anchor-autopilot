"""The Music Studio (Jarvis) makes songs with ANCHOR's own pipeline (anchor/studio.py).

Anchit, 2026-11-20: "Music studio in jarvis must use this exact architecture and logics to
create music based on the prompts given"."""
import json
from pathlib import Path

import pytest

from anchor import studio
from anchor.config import load_profile

P = load_profile()
LYRICS = ("[Intro]\nHold my hand\n\n[Verse 1]\nWe walked in when the gates were gold\nThe bass came up through our shoes\n"
          "Every stranger was a friend\nEvery light a colour we could use\n\n[Chorus]\nDance till the sun comes up\n"
          "Nobody leaves till the morning\n\n[Verse 2]\nYour hair was full of laser smoke\nWe laughed until we lost our names\n\n"
          "[Bridge]\nOne more song\n\n[Outro]\nHold my hand")


@pytest.mark.parametrize("genre,prompt,lane", [
    ("Acid Psychedelic Techno", "anything", "acidpsy"),
    ("hardstyletechno", "anything", "hardstyletechno"),
    ("", "a psychedelic acid 303 rave at sunrise", "acidpsy"),
    ("", "hard hitting rap over raw industrial hard tech", "hardtechrap"),
    ("", "rawstyle anthem for the main stage", "rawbounce"),
    ("", "drift phonk with cowbells", "phonktechno"),
    ("", "a love song", "hardtech"),
])
def test_the_prompt_picks_a_decided_genre(genre, prompt, lane):
    assert studio.lane_for(P, {"genre": genre, "prompt": prompt}) == lane


def test_a_studio_brief_is_a_drop_brief_for_the_users_song():
    req = {"id": "t0001", "prompt": "an acid psychedelic rave until sunrise", "title": "Sun Comes Up", "lyrics": LYRICS}
    b = studio.brief_maker(P, req)(0, (), "")
    assert b["lane"] == "acidpsy" and b["lane_name"] == "Acid Psychedelic Techno"
    assert b["genre_line"].startswith("Acid Psychedelic Techno")
    assert b["title"] == "Sun Comes Up" and b["arrangement"] == "club"
    assert "[Drop]\nSun Comes Up!" in b["lyrics"] and "sparse" in b["caption"]
    assert P.lane("acidpsy").bpm[0] <= b["bpm"] <= P.lane("acidpsy").bpm[1]
    # a different request draws a different record
    other = studio.brief_maker(P, {**req, "id": "t0002"})(0, (), "")
    assert other["seed"] != b["seed"]


def test_rap_keeps_its_verses_and_no_lyrics_is_instrumental():
    rap = studio.brief_maker(P, {"id": "t0003", "prompt": "rap over raw hard tech", "lyrics": LYRICS})(0, (), "")
    assert rap["genre_group"] == "rap" and rap["arrangement"] == "song" and "Verse 2" in rap["lyrics"]
    inst = studio.brief_maker(P, {"id": "t0004", "prompt": "hard techno rawstyle"})(0, (), "")
    assert inst["arrangement"] == "instrumental" and inst["lyrics"] == "" and "instrumental" in inst["caption"]


@pytest.mark.parametrize("bad", [{}, {"id": "x", "prompt": "a"}, {"id": "good1", "prompt": " "},
                                 {"id": "bad id!", "prompt": "a"}, {"id": "good1", "prompt": "a", "lyrics": "x" * 7000}])
def test_bad_requests_are_refused(bad):
    with pytest.raises(ValueError):
        studio.validate(bad)


def test_the_workflow_runs_on_the_mac_and_hands_back_a_release():
    wf = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "studio.yml").read_text()
    assert "anchor-mac" in wf and "python -m anchor studio" in wf and 'gh release create "studio-$ID"' in wf
    assert "--prerelease" in wf
    for name in ("daily.yml", "publish-queue.yml"):
        text = (Path(wf and __file__).resolve().parent.parent / ".github" / "workflows" / name).read_text()
        assert "--limit 60" in text and "grep '^drop-'" in text, "studio releases never push drops off the list"


@pytest.mark.slow
def test_a_studio_song_end_to_end_with_the_test_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_SEED_SALT", "")
    req = {"id": "t0005", "prompt": "an acid psychedelic rave until sunrise", "title": "Sun Comes Up", "lyrics": LYRICS}
    meta = studio.run(P, req, tmp_path, engine_name="fixture")
    assert (tmp_path / meta["mp3"]).stat().st_size > 100_000
    saved = json.loads((tmp_path / "studio.json").read_text())
    assert saved["genre"] == "Acid Psychedelic Techno" and saved["qc"]["attempts"]
