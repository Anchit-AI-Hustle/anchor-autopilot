"""Different melodies and sounds on every song (Anchit, 2026-10-31: "different melodies,
sounds, everything")."""
from collections import Counter
from datetime import date, timedelta

from anchor.brief import PALETTE_GAP, PALETTE_PARTS, make_brief, pick_palette
from anchor.config import load_profile
from anchor.util import rng


def test_each_song_gets_its_own_lead_bass_drums_melody_and_chords_in_the_prompt():
    p = load_profile()
    b = make_brief(p, "2026-11-01", [])
    s = b["sound"]
    assert set(s) == set(PALETTE_PARTS)
    for part in PALETTE_PARTS:
        assert s[part] in b["caption"], part


def test_no_lead_or_melody_comes_back_within_eight_songs_and_no_set_repeats():
    p = load_profile()
    hist, sets = [], []
    for i in range(150):
        s = pick_palette(p, rng("anchor-sound", i), hist)
        for prev in hist[:PALETTE_GAP]:
            assert s["lead"] != prev["sound"]["lead"] and s["melody"] != prev["sound"]["melody"], i
        sets.append(tuple(s[k] for k in PALETTE_PARTS))
        hist.insert(0, {"sound": s})
    assert len(set(sets)) == len(sets), "no two songs share the whole sound"
    leads = Counter(x[0] for x in sets)
    assert len(leads) == len(p.music["palette"]["leads"]), "every lead sound gets used"


def test_keys_are_minor_and_major():
    keys = load_profile().music["keys"]
    assert sum(k.endswith("major") for k in keys) >= 6 and sum(k.endswith("minor") for k in keys) >= 6
    p = load_profile()
    got = {make_brief(p, (date(2026, 11, 1) + timedelta(days=n)).isoformat(), [])["key"].split()[-1] for n in range(30)}
    assert got == {"major", "minor"}


def test_each_genre_group_draws_its_own_beat_and_sounds():
    """Anchit, 2026-11-01: complete beats and sounds as per the genres."""
    import random
    from anchor.brief import pick_palette
    p = load_profile()
    pal = p.music["palette"]
    for group in ("hardtech", "psy", "rap", "hiphop"):
        bank = pal[group]
        for _ in range(20):
            s = pick_palette(p, random.Random(_), [], group=group)
            assert s["drums"] in bank["drums"] and s["bass"] in bank["basses"] and s["lead"] in bank["leads"]
    assert any("boom bap" in d or "trap" in d for d in pal["hiphop"]["drums"])
    assert "808" in " ".join(pal["hiphop"]["basses"])
    assert any("psy" in d for d in pal["psy"]["drums"])
    assert any("rawstyle" in d or "rumbl" in d for d in pal["hardtech"]["drums"])


def test_a_brief_carries_its_genre_groups_sound():
    from datetime import date, timedelta
    from anchor.brief import make_brief
    p = load_profile()
    for i in range(30):
        b = make_brief(p, (date(2026, 11, 1) + timedelta(days=i)).isoformat(), [])
        lane = p.lane(b["lane"])
        group = lane.group
        if lane.palette:
            # the decided genres bring their own instruments (artist/lanes.toml, 2026-11-21)
            assert b["sound"]["drums"] in lane.palette["drums"], (b["lane"], b["sound"])
        elif group in p.music["palette"] and isinstance(p.music["palette"][group], dict):
            assert b["sound"]["drums"] in p.music["palette"][group]["drums"], (b["lane"], b["sound"])


def test_the_timbre_reference_matches_the_genre(tmp_path):
    from anchor.music import AceStepCpp
    # Anchit's major references (2026-11-20), and an old reference that is no longer used
    for name in ("ANCHOR-2026-11-07-outrun-your-shadow.mp3", "ANCHOR-legacy-kindness-needs-truth.mp3",
                 "ANCHOR-2026-11-10-move-before-thunder.mp3", "ANCHOR-2026-09-13-project-mayhem.mp3",
                 "ANCHOR-2026-09-04-then-do-it.mp3"):
        (tmp_path / name).write_bytes(b"x")
    groups = load_profile().music["ref_groups"]
    eng = AceStepCpp(tmp_path, tmp_path, "d", "l", ref_dir=tmp_path, ref_groups=groups)
    pick = lambda g: {eng.reference({"seed": s, "genre_group": g}).name for s in range(8)}
    assert pick("hardtech") == {"ANCHOR-2026-09-13-project-mayhem.mp3", "ANCHOR-legacy-kindness-needs-truth.mp3"}
    assert pick("psy") == {"ANCHOR-2026-11-10-move-before-thunder.mp3", "ANCHOR-2026-09-13-project-mayhem.mp3"}
    assert pick("rap") == {"ANCHOR-2026-11-07-outrun-your-shadow.mp3", "ANCHOR-2026-11-10-move-before-thunder.mp3"}
    assert eng.reference({"seed": 3, "genre_group": "hiphop"}) is None


def test_a_half_time_beat_keeps_its_tempo():
    from anchor.audio import same_octave
    assert same_octave(90.0, 180) == 180.0
    assert same_octave(176.0, 176) == 176.0
    assert same_octave(150.0, 172) == 150.0
