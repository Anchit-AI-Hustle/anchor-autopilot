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
    assert "[Instrumental]" not in a["caption"] and "instrumental" in a["caption"]


def test_brief_rotation_rules_over_60_days():
    p = load_profile()
    hist = list(reversed(_history(p, 60)))  # oldest first
    for prev, cur in zip(hist, hist[1:]):
        assert prev["lane"] != cur["lane"], "same lane two days running"
    for i in range(3, len(hist)):
        window = hist[i - 3:i]
        assert hist[i]["family"] not in {w["family"] for w in window}
        assert hist[i]["key"] not in {w["key"] for w in window}
    assert len({h["lane"] for h in hist}) == len(p.lanes), "every lane gets airtime"


def test_brief_description_and_bounds():
    p = load_profile()
    b = make_brief(p, "2026-10-01", [])
    lane = p.lane(b["lane"])
    assert lane.bpm[0] <= b["bpm"] <= lane.bpm[1]
    assert f"{b['bpm']} BPM" in b["description"] and b["key"] in b["description"]
    assert "#hardtechno" in b["description"] and "AI-assisted" in b["description"]
    assert len(b["youtube_title"]) <= 100
