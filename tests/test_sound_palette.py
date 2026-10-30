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
