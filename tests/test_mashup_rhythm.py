"""Mashups over 180 BPM are built for the body (artist/mashup_rhythm.md; Anchit, 2026-11-21:
"the mashup must be created after understanding the beats and syncing of the two genres before
mashing them up - understand the complete bpm synergising with the human body's different body
parts response to bpms")."""
import re

from anchor import genres, songbook
from anchor.brief import make_brief
from anchor.config import load_profile

SAY = ("kick on every beat", "two and four")


def mashups():
    return [l for l in load_profile().active_lanes if l.id in genres.MASHUPS]


def sound_words(lane):
    pal = " ".join(x for v in lane.palette.values() for x in v)
    return " ".join([lane.caption, lane.groove, pal, *lane.textures, *lane.special_moments]).lower()


def test_every_mashup_is_one_grid_with_a_half_time_backbone():
    for lane in mashups():
        assert lane.bpm[0] > 180, lane.id
        g = lane.groove.lower()
        assert all(w in g for w in SAY), (lane.id, lane.groove)
        if lane.voice != "rap":
            assert "running pace" in g and "per bar" in g, (lane.id, lane.groove)
        else:
            assert "rap's backbeat" in g, lane.id


def test_the_second_genre_is_slowed_to_fit_the_body():
    """At 184 BPM a sixteenth is 12 notes a second: a buzz, not a line. The acid, the sequences
    and the bass play eighths or eighth-note triplets; sixteenths only as slides and accents."""
    for lane in mashups():
        text = sound_words(lane).replace("sixteenth slides", "").replace("sixteenth hats", "")
        assert not re.search(r"sixteenth|16th", text), (lane.id, re.findall(r"[^,;]*sixteenth[^,;]*", text))
        assert "kick-bass-bass-bass" in lane.negative and "303 in straight sixteenths" in lane.negative


def test_the_rhythm_reaches_every_mashup_prompt():
    p = load_profile()
    for lane in mashups():
        for s in ("sky-belongs-to-nobody", "ribs-like-wings"):
            b = make_brief(p, "2026-11-22", [], 0, lane_id=lane.id, song=songbook.find(s))
            assert "claps on two and four" in b["caption"] or "metal hit on two and four" in b["caption"], lane.id
            assert len(b["caption"]) < 1700, (lane.id, len(b["caption"]))


def test_the_rhythm_is_written_down_with_its_sources():
    doc = open("artist/mashup_rhythm.md").read()
    for src in ("PMC4526248", "fnhum.2014.00903", "srep22774", "PMC1860846"):
        assert src in doc
