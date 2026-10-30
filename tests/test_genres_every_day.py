"""Every genre Anchit asked for, every day (2026-10-24: hard tech, psy, rap, hip hop and any
combinations; 2026-10-29: "ensure all songs for all genres as asked are created")."""
from collections import Counter
from datetime import date, timedelta

from anchor.brief import make_brief, slot_group, slot_lanes
from anchor.config import load_profile

GROUPS = {"hardtech", "psy", "rap", "hiphop"}


def test_each_active_lane_belongs_to_one_asked_genre():
    p = load_profile()
    assert {l.group for l in p.active_lanes} == GROUPS
    rap = [l for l in p.active_lanes if l.group in ("rap", "hiphop")]
    assert all(l.voice == "rap" for l in rap), "the rap and hip hop lanes rap their verses"
    assert {"hardtechrap", "psyhiphop", "psyrap"} <= {l.id for l in p.active_lanes}, "the combinations are lanes too"


def test_a_full_day_has_every_genre_and_the_lead_genre_turns():
    p = load_profile()
    leads = []
    for n in range(10):
        day = (date(2026, 11, 1) + timedelta(days=n)).isoformat()
        groups = [slot_group(p, day, s) for s in range(1, 6)]
        assert set(groups) == GROUPS | {"any"}, (day, groups)
        leads.append(groups[0])
        for s in range(1, 6):
            lanes = slot_lanes(p, day, s)
            assert lanes and (groups[s - 1] == "any" or {l.group for l in lanes} == {groups[s - 1]})
    assert set(leads) == GROUPS | {"any"}, "the first slot is a different genre each day"


def test_the_briefs_follow_the_slot_genres():
    p = load_profile()
    seen = Counter()
    for n in range(6):
        day = (date(2026, 11, 1) + timedelta(days=n)).isoformat()
        hist = []
        for s in range(1, 6):
            drop_id = day if s == 1 else f"{day}-{s}"
            b = make_brief(p, drop_id, hist)
            want = slot_group(p, day, s)
            assert want == "any" or b["genre_group"] == want, (drop_id, want, b["lane"])
            seen[b["genre_group"]] += 1
            hist.insert(0, {"id": drop_id, "date": day, "lane": b["lane"], "title": b["title"],
                            "family": b["family"], "key": b["key"]})
    assert all(seen[g] >= 6 for g in GROUPS), seen
