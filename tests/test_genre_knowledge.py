"""The genre and mashup knowledge (Anchit, 2026-11-10: "completely learn about each and every
genre ... and about mashups so that you can create the perfect type of music, songs, videos
and sets"). artist/genres.toml and artist/mashups.toml hold the researched facts; every lane
is checked against the genres it names, and the sets are ordered by tempo and key."""
from anchor import genres
from anchor.config import load_profile


def test_the_knowledge_is_complete_and_sourced():
    assert genres.problems() == []
    gs = genres.load()
    assert len(gs) >= 30
    fams = {g.family for g in gs.values()}
    assert {"techno", "hard dance", "psy", "bass", "house", "hiphop", "fusion"} <= fams
    # the channel's own sound, each with its tempo from the sources
    assert gs["hard_techno"].bpm == (140, 160) and gs["hardtek"].bpm == (150, 185)
    assert gs["psytrance"].bpm == (140, 148) and gs["frenchcore"].bpm[1] >= 200


def test_every_lane_makes_the_genres_it_names():
    """A lane called hard tech can never again be briefed as tech house: its tempo, words and
    negative prompt are checked against the researched genres it names."""
    p = load_profile()
    for raw in p.raw["music"]["lanes"]:
        if raw.get("retired"):
            continue
        lane = p.lane(raw["id"])
        assert raw.get("genres"), f"{lane.id} names no genres"
        assert genres.lane_problems(lane, raw["genres"], raw.get("tempo_like", [])) == [], lane.id


def test_a_wrong_brief_is_caught():
    p = load_profile()
    lane = p.lane("hardtech")
    soft = lane.__class__(**{**lane.__dict__, "caption": "tech house, swing shuffle, clean house kick, groovy bassline",
                             "genre_line": "Tech House", "style_line": "Tech House"})
    probs = genres.lane_problems(soft, ["hard_techno"])
    assert any("signature" in x for x in probs) and any("sound wrong" in x for x in probs)
    slow = lane.__class__(**{**lane.__dict__, "bpm": (124, 128)})
    assert any("bpm" in x for x in genres.lane_problems(slow, ["hard_techno"]))


def test_mashup_lanes_fuse_two_genres_on_a_hard_techno_base():
    p = load_profile()
    ids = {l.id for l in p.active_lanes}
    assert {"hardstyletechno", "phonktechno"} <= ids
    recipes = {(f["base"], f["top"]) for f in genres.mashups()["fusion"]}
    assert ("hard_techno", "hardstyle") in recipes and ("hard_techno", "phonk") in recipes
    assert ("hard_techno", "techno_rap") in recipes
    assert genres.label(["hard_techno", "phonk"]) == "Drift Phonk x Hard Techno"


def test_camelot_wheel_and_tempo_rules():
    codes = genres.mashups()["camelot"]["codes"]
    assert len(set(codes.values())) == 24
    assert genres.camelot("A minor") == "8A" and genres.camelot("C major") == "8B"
    assert genres.key_distance("A minor", "C major") == 0      # relative keys
    assert genres.key_distance("A minor", "E minor") == 1      # one step
    assert genres.key_distance("A minor", "D minor") == 1
    assert genres.key_distance("B minor", "A# minor") == 5
    assert genres.key_distance("A minor", None) == 9
    p = load_profile()
    assert all(genres.camelot(k) for k in p.music["keys"]), "every key a song can be in has a code"
    assert genres.tempo_ok(150, 75) and genres.tempo_ok(160, 166) and not genres.tempo_ok(160, 175)


def test_a_set_climbs_to_a_peak_two_thirds_in_and_moves_in_key():
    keys = ["A minor", "E minor", "F minor", "C major", "B minor", "G minor", "D minor", "F# minor", "C minor"]
    tracks = [{"id": str(i), "bpm": 160 + 2 * i, "key": k, "date": f"2026-11-0{i + 1}"} for i, k in enumerate(keys)]
    order = genres.set_order(list(reversed(tracks)))
    bpms = [t["bpm"] for t in order]
    top = bpms.index(max(bpms))
    assert 0.5 <= top / (len(bpms) - 1) <= 0.85, bpms
    assert bpms[0] == min(bpms) and bpms[top + 1:] == sorted(bpms[top + 1:], reverse=True)
    assert sorted(t["id"] for t in order) == sorted(t["id"] for t in tracks)
    # among near tempos the next song is the closest key
    climb = order[:top]
    steps = [genres.key_distance(a["key"], b["key"]) for a, b in zip(climb, climb[1:])]
    assert sum(steps) <= sum(genres.key_distance(a["key"], b["key"]) for a, b in zip(tracks, tracks[1:]))
    assert genres.set_order(tracks[:2]) == tracks[:2]
    # a short set just climbs (the weekly mix of three songs, tests/test_mix_youtube.py)
    assert [t["bpm"] for t in genres.set_order(list(reversed(tracks[:4])))] == [160, 162, 164, 166]


def test_his_own_songs_are_filed_by_what_they_are():
    """Anchit's Suno style prompts, filed by their sound and voice (2026-11-10)."""
    cases = {
        "hardtechno with psychedelic trance crossover, relentless 150 BPM four-on-the-floor kick, "
        "aggressive rhythmic rap verses with clipped confident delivery": "psyrap",           # Red Dust Warning
        "Fast-paced cinematic chopper rap fused with peak-time hard acid techno and organic psytrance": "psyrap",
        "hard techno, rawstyle hybrid, industrial, 156-158 bpm": "rawbounce",                  # Project Mayhem Part 2
        "Hard techno, relentlessly fast bounce at 200 BPM and above, acid arpeggiator": "hyper",
        "Hard techno, industrial techno, peak-time hypnotic techno, 154 BPM, powerful distorted kick": "hardtech",
        "Rap, brooding half-time trap bounce, snare-clap backbeat": "hiphoptechno",
        "drift phonk cowbell over hard techno": "phonktechno",
        "aggressive rap over industrial hard techno, distorted kick": "hardtechrap",
    }
    for tags, lane in cases.items():
        assert genres.classify(tags) == lane, (tags[:40], genres.classify(tags))
    p = load_profile()
    ids = {l.id for l in p.active_lanes}
    assert set(cases.values()) <= ids
