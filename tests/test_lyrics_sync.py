"""Words the ear missed are placed beside the sung ones, never alone over the music (2026-11-08)."""
from anchor.lyrics import snap_to_sheet


def test_missed_words_stay_with_their_section_not_spread_over_the_music():
    sheet = "[Intro]\nCan you outrun your own shadow?\n\n[Verse 1]\nI've been running from ghosts in the back of my head"
    heard = [("can", 15.5, 15.8), ("you", 19.0, 19.2), ("outrun", 19.3, 19.8), ("your", 19.9, 20.1),
             ("own", 22.2, 22.4), ("shadow", 22.6, 23.3),
             ("from", 79.9, 80.1), ("ghosts", 80.1, 80.4), ("in", 80.4, 80.5), ("the", 80.5, 80.6),
             ("back", 80.6, 80.8), ("of", 80.8, 80.9), ("my", 80.9, 81.0), ("head", 81.0, 81.3)]
    out = {w: s for w, s, e in snap_to_sheet(heard, sheet)}
    for w in ("I've", "been", "running"):
        assert 78.0 < out[w] < 79.9, (w, out[w])         # just before "from", not over the intro music


def test_a_fast_verse_still_spreads_evenly():
    sheet = "[Verse]\none two three four five six seven eight"
    heard = [("one", 1.0, 1.1), ("two", 1.2, 1.3), ("three", 1.4, 1.5), ("seven", 2.4, 2.5), ("eight", 2.6, 2.7)]
    out = snap_to_sheet(heard, sheet)
    times = [s for w, s, e in out]
    assert times == sorted(times) and 1.5 <= times[3] < times[5] < 2.4    # four to six fill the short gap
