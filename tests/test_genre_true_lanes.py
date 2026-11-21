"""Every decided genre and mashup sounds like itself (Anchit, 2026-11-21: "rap songs are still
attrocious - mashups are incorrect - there is no sync in the music and the lyrics in the song -
Sky Belongs to Nobody - still wrong creation as per genre mentioned too")."""
import re

from anchor import genres, songbook
from anchor.brief import make_brief
from anchor.config import load_profile

# words of other genres that put Sky Belongs To Nobody in the wrong world
FOREIGN = {
    "all": ("rawstyle", "hardstyle", "hypertechno", "arcade", "chiptune", "brass", "power chords", "clav",
            "major chords", "bouncy, fun", "wacky", "double time", "double-time", "riding the hats"),
    "industrialtechno": ("303", "acid", "psychedelic"),
    "hardtechrap": ("303", "acid", "psychedelic"),
    "warehouse": ("303", "psychedelic"),
    "hardtech": ("swing", "swung"),
    "raptechno": ("psychedelic",),
}


def briefs(lane_id, songs=("sky-belongs-to-nobody", "stop-the-rewind", "ribs-like-wings")):
    p = load_profile()
    return [make_brief(p, "2026-11-22", [], 0, lane_id=lane_id, song=songbook.find(s)) for s in songs]


def instruments_and_genre(caption):
    """The layers that say what the record is made of (the vocals and mood speak of people)."""
    return ". ".join(x for x in caption.split(". ") if not x.startswith(("Vocals", "Mood")))


def test_only_the_decided_genres_are_drawn_and_every_one_has_its_own_definition():
    p = load_profile()
    assert {l.id for l in p.active_lanes} == set(genres.DECIDED) | set(genres.MASHUPS)
    for lane in p.active_lanes:
        assert lane.palette and lane.feel, lane.id
        for part in ("leads", "basses", "drums", "melodies", "chords"):
            assert lane.palette.get(part), (lane.id, part)
        if lane.id in genres.MASHUPS:
            assert lane.bpm[0] > 180, lane.id


def test_no_lane_borrows_another_genres_sound():
    p = load_profile()
    for lane in p.active_lanes:
        banned = FOREIGN["all"] + FOREIGN.get(lane.id, ())
        for b in briefs(lane.id):
            # "with no swing" names what the lane is not
            text = instruments_and_genre(b["caption"]).lower().replace("no swing", "")
            hit = [w for w in banned if w in text]
            assert not hit, (lane.id, hit, b["caption"])


def test_a_rap_at_mashup_speed_rides_the_half_time_pocket():
    p = load_profile()
    for lane in (l for l in p.active_lanes if l.voice == "rap"):
        assert "{half}" in lane.flow, lane.id
        for b in briefs(lane.id):
            bpm = int(b["bpm"])
            assert f"half-time pocket at {round(bpm / 2)} BPM" in b["caption"], (lane.id, bpm)
            assert "one lyric line per half-time bar" in b["caption"]
            vocals = next(x for x in b["caption"].split(". ") if x.startswith("Vocals"))
            assert "clipped confident delivery" in vocals and "double time" not in vocals, vocals
            assert re.search(r"\band a,|\bwith a,|\bof a,", vocals) is None, vocals


def test_sky_belongs_to_nobody_is_industrial_hard_rap():
    b = briefs("hardtechrap", ("sky-belongs-to-nobody",))[0]
    cap = b["caption"]
    assert cap.startswith("hard rap over industrial techno")
    assert "Feel: hungry, defiant and mechanical" in cap and "bouncy, fun and psychedelic" not in cap
    assert b["arrangement"] == "song" and b["lyrics"].count("The sky belongs to nobody") >= 2


def test_every_caption_stays_inside_the_budget():
    p = load_profile()
    for lane in p.active_lanes:
        for s in songbook.load()[::9]:
            b = make_brief(p, "2026-11-22", [], 0, lane_id=lane.id, song=s)
            assert len(b["caption"]) < 1700, (lane.id, s.id, len(b["caption"]))
