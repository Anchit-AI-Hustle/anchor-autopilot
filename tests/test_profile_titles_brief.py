from datetime import date, timedelta

import pytest

from anchor.brief import make_brief
from anchor.config import load_profile, validate
from anchor.titles import make_title
from anchor.util import rng


def test_profile_loads_and_validates():
    p = load_profile()
    assert p.artist["name"] == "ANCHOR"
    assert p.artist["youtube_channel_id"] == "UCAKPJrMOwspkOXY1aLKaAkQ"
    assert len(p.lanes) >= 4 and len(p.families) >= 4
    assert p.youtube["ai_generated"] is True, "AI disclosure must stay on"


def test_profile_rejects_bad_values():
    p = load_profile()
    raw = dict(p.raw)
    raw["music"] = dict(raw["music"], short_s=999)
    with pytest.raises(ValueError):
        validate(raw, p.lanes, p.families)


def test_titles_unique_for_a_year_and_never_reuse_existing():
    p = load_profile()
    used = list(p.artist["existing_titles"])
    titles = []
    for day in range(365):
        t = make_title(p.titles, rng("t", day), used, titles[-10:])
        words = [w.lower() for w in t.split()]
        assert len(words) == len(set(words)), t
        assert t.lower() not in {u.lower() for u in used}
        used.append(t)
        titles.append(t)
    assert len(set(titles)) == 365


def _history(p, days):
    hist = []
    start = date(2026, 9, 11)
    for i in range(days):
        day = (start + timedelta(days=i)).isoformat()
        b = make_brief(p, day, hist)
        hist.insert(0, {"date": day, "title": b["title"], "lane": b["lane"], "family": b["family"], "key": b["key"]})
    return hist


def test_brief_is_deterministic():
    p = load_profile()
    a = make_brief(p, "2026-09-11", [])
    b = make_brief(p, "2026-09-11", [])
    assert a == b
    assert a["post_at"] == "2026-09-11T17:30:00Z"
    assert "[Instrumental]" not in a["caption"] and "Vocals: whispers" in a["caption"]


def test_style_prompt_carries_all_nine_layers():
    """The producer's brief describes the record, layer by layer, and never a vague idea."""
    p = load_profile()
    b = make_brief(p, "2026-09-16", [])
    lane = p.lane(b["lane"])
    cap = b["caption"]
    for layer in (lane.caption, lane.era, "Mood: " + b["mood"], f"{b['bpm']} BPM", lane.groove,
                  "Instruments:", p.music["vocals"], "Production: " + lane.production,
                  "Arrangement:", "Special moment: " + b["special"]):
        assert layer in cap, f"layer missing from style prompt: {layer[:40]}"
    for t in b["textures"]:
        assert t in cap and t in b["lyrics"], "the day's textures are placed in both sheets"
    assert b["lyrics"].splitlines()[0].startswith("[intro - "), "songwriter gets section directions"
    assert len(cap) < 1400, "compressed prose, not the design headings"


def test_every_brief_stays_compressed():
    """Every day's prompt, in every lane, stays inside the budget, not just one sample day."""
    p = load_profile()
    start = date(2026, 10, 1)
    for i in range(120):
        b = make_brief(p, (start + timedelta(days=i)).isoformat(), [])
        assert len(b["caption"]) < 1400, f"{b['date']} ({b['lane']}): {len(b['caption'])} chars"


DARK = ("dark", "menac", "oppressive", "dread", "cold", "hostile", "claustrophob", "gloom",
        "dystopi", "paranoid", "brutal", "fury", "hollow", "exhausted", "grim")


def test_songs_are_briefed_bouncy_and_fun():
    """Anchit, 2026-10-04: songs must be more bouncy and more fun. Every lane's sound layers
    carry bounce, the channel-wide feel rides in every prompt, and nothing the model is told
    to make sounds dark or menacing (the genre and SEO lines are left alone)."""
    p = load_profile()
    feel = p.music["feel"]
    assert "bouncy" in feel and "fun" in feel
    assert "gloomy" in p.music["negative"] and "trance uplift" not in p.music["negative"]
    assert "never dark" in feel
    for lane in p.active_lanes:
        sound = " ".join([lane.caption, lane.era, lane.groove, lane.production,
                          *lane.mood_arcs, *lane.special_moments, *lane.textures]).lower()
        assert "bounc" in lane.caption.lower() and "bounc" in lane.groove.lower(), lane.id
        hits = [w for w in DARK if w in sound]
        assert not hits, f"lane {lane.id} still briefs {hits}"
    start = date(2026, 10, 1)
    for i in range(30):
        b = make_brief(p, (start + timedelta(days=i)).isoformat(), [])
        assert f"Feel: {feel}" in b["caption"], b["date"]
        said = b["caption"].replace(feel, "").lower() + b["lyrics"].lower()
        assert not [w for w in DARK if w in said], b["date"]
        assert "bouncing bass" in b["caption"]


def test_style_prompt_rotates_within_a_lane():
    """Two days in the same lane must not be the same record with a different date."""
    p = load_profile()
    briefs = [make_brief(p, f"2026-10-{d:02d}", []) for d in range(1, 29)]
    by_lane: dict[str, list[dict]] = {}
    for b in briefs:
        by_lane.setdefault(b["lane"], []).append(b)
    for lane_id, bs in by_lane.items():
        if len(bs) < 3:
            continue
        assert len({b["caption"] for b in bs}) == len(bs), f"{lane_id}: identical captions"
        assert len({(b["mood"], b["special"], tuple(b["textures"])) for b in bs}) > 1


def test_brief_rotation_rules_over_60_days():
    p = load_profile()
    hist = list(reversed(_history(p, 60)))  # oldest first
    for prev, cur in zip(hist, hist[1:]):
        assert prev["lane"] != cur["lane"], "same lane two days running"
    for i in range(3, len(hist)):
        window = hist[i - 3:i]
        assert hist[i]["family"] not in {w["family"] for w in window}
        assert hist[i]["key"] not in {w["key"] for w in window}
    assert len({h["lane"] for h in hist}) == len(p.active_lanes), "every active lane gets airtime"


def test_brief_description_and_bounds():
    p = load_profile()
    b = make_brief(p, "2026-10-01", [])
    lane = p.lane(b["lane"])
    assert lane.bpm[0] <= b["bpm"] <= lane.bpm[1]
    # the key is measured and kept in the data for QC, but never shown to a listener
    assert f"{b['bpm']} BPM" in b["description"] and b["key"] not in b["description"]
    assert "#hardtechno" in b["description"] and "AI use disclosed" in b["description"]
    assert len(b["youtube_title"]) <= 100


def test_every_song_is_hard_acid_or_psychedelic_at_160_to_200_bpm():
    """Anchit, 2026-10-04: hard techno and acid psychedelic vibes, 160-200 BPM, with bounce."""
    p = load_profile()
    for lane in p.active_lanes:
        assert 160 <= lane.bpm[0] <= lane.bpm[1] <= 200, (lane.id, lane.bpm)
        style = (lane.caption + " " + lane.genre_line).lower()
        assert any(w in style for w in ("hard techno", "acid", "psychedelic", "hyper")), lane.id
    lanes = " ".join(l.genre_line.lower() for l in p.active_lanes)
    assert "acid techno" in lanes and "psychedelic techno" in lanes and "hard techno" in lanes
    assert {l.bpm[1] for l in p.active_lanes} & set(range(195, 201)), "the top of the range is used"
    start = date(2026, 10, 1)
    seen = set()
    for i in range(120):
        b = make_brief(p, (start + timedelta(days=i)).isoformat(), [])
        assert 160 <= b["bpm"] <= 200
        seen.add(b["lane"])
    assert seen == {l.id for l in p.active_lanes}


def test_songs_whisper_in_the_quiet_parts_and_chant_the_title_in_the_drops():
    """Anchit, 2026-10-04: whispers or lyrics as chants."""
    from anchor.music import AceStepCpp
    p = load_profile()
    assert "vocals" not in p.music["negative"].split(", ") and "lyrics" not in p.music["negative"]
    for i in range(1, 29):
        b = make_brief(p, f"2026-10-{i:02d}", [])
        sections = b["lyrics"].split("\n\n")
        chant = b["title"].upper()
        for sec in sections:
            tag, *words = sec.split("\n")
            assert tag.startswith("[") and tag.endswith("]") and words and all(w.strip() for w in words), sec
            if tag.startswith("[drop "):
                assert "shouted crowd chant" in tag and words[0] == f"{chant}! {chant}!"
            if tag.startswith(("[intro ", "[breakdown ", "[outro ")):
                assert "whispered voice" in tag and words[0] in p.music["voice"]["whispers"]
        assert sum(1 for s_ in sections if s_.startswith("[drop ")) >= 1
        assert b["vocal_style"] and "chant" in b["vocal_style"]
        req = AceStepCpp("bin", "models", "dit", None).request(b)
        assert req["vocal_language"] == "en" and req["lyrics"] == b["lyrics"]
        assert len(b["lyrics"]) < 2500


def test_records_already_out_keep_their_own_genre():
    """The old lanes are retired, not rewritten: a drop on record as "industrial" still reads
    Industrial Hard Techno in titles, mixes and the weekly retitle, and is never drawn again."""
    from anchor.seo import genre_phrase
    p = load_profile()
    old = {"industrial": "Industrial Hard Techno", "rawstyle": "Rawstyle Hybrid", "hypnotic": "Hypnotic Techno",
           "acid": "Acid Techno", "bunker": "Dark Techno", "cyber": "Cyberpunk Techno"}
    for lane_id, phrase in old.items():
        lane = p.lane(lane_id)
        assert lane.retired and genre_phrase(lane) == phrase and lane not in p.active_lanes
    assert not ({l.id for l in p.active_lanes} & set(old))
    start = date(2026, 10, 1)
    for i in range(60):
        assert make_brief(p, (start + timedelta(days=i)).isoformat(), [])["lane"] not in old
