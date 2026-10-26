"""Original titles and the hard tech, rap and hip hop lanes (Anchit, 2026-10-24).

The catalogues are faked: nothing here touches the network."""
from datetime import date, timedelta

import pytest

from anchor import originality
from anchor.brief import make_brief
from anchor.config import load_profile
from anchor.titles import make_title
from anchor.util import rng

# what the three catalogues answered for real on 2026-10-24 (trimmed to the matching titles)
KNOWN = {"victory lap": 40, "stay with me": 37, "overload protocol": 24, "comet": 25}


def fake_http(answers=KNOWN, down=()):
    """A stand-in for originality._get that answers like the three catalogues do."""
    calls = []

    def http(source, url):
        calls.append(source)
        if source in down:
            return None
        import urllib.parse
        q = urllib.parse.unquote_plus(url.split("?", 1)[1])
        title = q.split('"')[1] if '"' in q else q.split("term=")[1].split("&")[0]
        n = answers.get(originality.norm(title), 0)
        hit = {"title": title, "trackName": title}
        rows = [dict(hit) for _ in range(n)] + [{"title": title + " Remix Pack", "trackName": "Other Song"}]
        return {"musicbrainz": {"recordings": rows}, "itunes": {"results": rows},
                "deezer": {"data": rows}}[source]
    http.calls = calls
    return http


def test_norm_strips_credits_and_versions():
    assert originality.norm("Victory Lap (feat. Stacy Barthe)") == "victory lap"
    assert originality.norm("VICTORY LAP - Radio Edit") == "victory lap"
    assert originality.norm("Victory Lap [Remix]") == "victory lap"
    assert originality.norm("Rock & Roll") == "rock and roll"
    assert originality.norm("Victory Lap Five") != "victory lap"


def test_a_famous_title_is_taken_and_a_new_one_is_free():
    assert originality.taken("Victory Lap", fake_http()) is True
    assert originality.taken("Overload Protocol", fake_http()) is True
    assert originality.taken("Detonate Iron", fake_http()) is False


def test_one_catalogue_down_still_decides_and_all_down_is_unknown():
    assert originality.taken("Victory Lap", fake_http(down=("musicbrainz",))) is True
    assert originality.taken("Detonate Iron", fake_http(down=("musicbrainz", "itunes"))) is False
    assert originality.taken("Detonate Iron", fake_http(down=("musicbrainz", "itunes", "deezer"))) is None


def test_lookup_stops_at_the_first_catalogue_that_has_it():
    http = fake_http()
    originality.lookup("Victory Lap", http)
    assert http.calls == ["musicbrainz"]


def test_make_title_skips_titles_that_are_already_songs():
    bank = {"patterns": [["PH", 1]], "verbs": [], "nouns": [], "adjectives": [],
            "phrases": ["Victory Lap", "Stay With Me", "Detonate Iron"]}
    report = {}
    t = make_title(bank, rng("t", 1), [], [], taken=lambda s: originality.taken(s, fake_http()), report=report)
    assert t == "Detonate Iron"
    assert set(report["rejected"]) <= {"Victory Lap", "Stay With Me"} and report["verified"] is True


def test_make_title_gives_up_loudly_rather_than_reusing_a_famous_title():
    bank = {"patterns": [["PH", 1]], "verbs": [], "nouns": [], "adjectives": [],
            "phrases": ["Victory Lap", "Stay With Me"]}
    with pytest.raises(RuntimeError):
        make_title(bank, rng("t", 1), [], [], taken=lambda s: True, max_checks=5)


def test_an_unverified_title_is_reported_as_such():
    p = load_profile()
    report = {}
    make_title(p.titles, rng("t", 2), [], [], taken=lambda s: None, report=report)
    assert report["verified"] is False and report["checked"] == 1


def test_the_brief_runs_the_check_and_records_it(monkeypatch):
    monkeypatch.setenv("ANCHOR_TITLE_CHECK", "1")
    seen = []
    monkeypatch.setattr(originality, "taken", lambda t: seen.append(t) or (len(seen) < 3))
    b = make_brief(load_profile(), "2026-10-25", [])
    assert len(seen) == 3 and b["title"] == seen[-1]
    assert b["title_check"]["rejected"] == seen[:2] and b["title_check"]["verified"] is True


def test_the_check_is_off_in_tests_and_on_by_default(monkeypatch):
    assert originality.checker() is None
    monkeypatch.delenv("ANCHOR_TITLE_CHECK")
    assert originality.checker() is originality.taken


def test_no_one_word_titles():
    p = load_profile()
    assert all(pat != "N" for pat, _ in p.titles["patterns"])
    used = []
    for day in range(200):
        t = make_title(p.titles, rng("t", day), used, used[-10:])
        assert len(t.split()) >= 2, t
        used.append(t)


def test_hard_tech_psy_rap_and_hip_hop_all_get_airtime():
    p = load_profile()
    ids = {l.id for l in p.active_lanes}
    assert {"hardtech", "psytech", "raptechno", "hiphoptechno", "psyrap"} <= ids
    seen, rap_days = set(), 0
    start = date(2026, 10, 25)
    hist = []
    for i in range(90):
        day = (start + timedelta(days=i)).isoformat()
        b = make_brief(p, day, hist)
        hist.insert(0, {"date": day, "title": b["title"], "lane": b["lane"], "family": b["family"], "key": b["key"]})
        seen.add(b["lane"])
        rap_days += p.lane(b["lane"]).voice == "rap"
        assert 160 <= b["bpm"] <= 200, "the new lanes keep the channel's tempo range"
    assert seen == ids
    assert 15 <= rap_days <= 45, rap_days


def test_rap_lanes_rap_and_never_ban_rap():
    p = load_profile()
    for lane in p.active_lanes:
        if lane.voice != "rap":
            assert lane.vocals == "" and lane.negative == ""
            continue
        assert "rap verses" not in lane.negative and "sung melody" in lane.negative
        assert "rap" in lane.vocals.lower() and "chant" in lane.vocals
    bars = p.music["voice"]["rap"]
    assert len(bars) == len(set(bars)) >= 24
    for i in range(1, 60):
        b = make_brief(p, (date(2026, 11, 1) + timedelta(days=i)).isoformat(), [])
        lane = p.lane(b["lane"])
        if lane.voice != "rap":
            assert "rap verse" not in b["lyrics"] and "rap verses" in b["negative"]
            continue
        assert "rap verses" not in b["negative"] and lane.vocals in b["caption"]
        verses = [s for s in b["lyrics"].split("\n\n") if s.split("\n")[0] == "[Verse]"]
        assert verses, b["date"]
        lines = [w for v in verses for w in v.split("\n")[1:]]
        assert len(lines) == len(set(lines)) or len(verses) > 3, "no bar repeats inside a song"
        assert f"{b['title'].upper()}! {b['title'].upper()}!" in b["lyrics"], "the title is still the hook"
