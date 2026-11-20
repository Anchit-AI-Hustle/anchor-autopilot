"""Genre listings match the decided genres, and chant lanes sing a club cut.

Anchit, 2026-11-20: "songs generated and their genres listings must be correct as per the
genres decided". The decided genre of a song is its lane: the YouTube title, the description's
search line, the site and Jarvis all say the lane's own name, and the rest of the genre line
lists only the genres the lane is built from (artist/genres.toml), nothing borrowed.

Anchit, 2026-11-15: "all songs dont need to have constant lyrics throughout the song - that is
probably stopping the best acid techno and hard techno flows and even in the drops".
"""
import re

from anchor import genres, seo, songbook, songbook_club
from anchor.brief import make_brief
from anchor.config import load_profile

P = load_profile()
ACTIVE = [l for l in P.lanes if not l.retired and l.group]


def test_every_listing_says_the_lanes_own_genre():
    gs = genres.load()
    for lane in ACTIVE:
        phrases = [x.strip() for x in lane.genre_line.split(",")]
        assert phrases[0] == lane.name, (lane.id, phrases)
        allowed = {gs[g].name.lower() for g in genres.for_lane(P, lane.id)} | {"hardtek"}
        extra = [x for x in phrases[1:] if x.lower() not in allowed]
        assert not extra, f"{lane.id} lists genres it is not built from: {extra}"
        assert seo.youtube_title("Song", lane, 170, "ANCHOR") == f"Song | {lane.name} | ANCHOR"


def test_a_suno_song_is_listed_under_the_lane_it_is_filed_in():
    lane = P.lane(genres.classify("acid techno, psychedelic, 303, female vocals", 170))
    assert lane.genre_line.split(",")[0] == lane.name == "Acid Psychedelic Techno"


def _club_song():
    return next(s for s in songbook.load() if "psy" in s.groups and s.form != "vibe" and songbook.words(s) > 300)


def test_the_club_cut_is_mostly_music():
    song = _club_song()
    sheet = songbook_club.club_cut(song, "psy")
    tags = re.findall(r"^\[([^\]]+)\]$", sheet, re.M)
    assert tags == ["Intro", "Verse 1", "Build-Up", "Drop", "Breakdown", "Build-Up", "Drop", "Outro"]
    words = songbook_club.sung_words(sheet)
    assert words <= songbook.words(song) * 0.4, (words, songbook.words(song))
    # each drop carries one shout, never a verse (an empty section can render as silence)
    drops = re.findall(r"\[Drop\]\n([^\[]*)", sheet)
    assert all(d.strip() == f"{song.title}!" for d in drops)
    # the name the lyric check listens for is sung in the build-up
    build = re.search(r"\[Build-Up\]\n([^\[]*)", sheet).group(1).lower()
    assert any(w in build for w in songbook_club._title_words(song.title))


def test_hard_tech_breaks_on_one_spoken_line_before_the_climax():
    song = next(s for s in songbook.load() if "hardtech" in s.groups and s.form != "vibe")
    sheet = songbook_club.club_cut(song, "hardtech")
    second_build = sheet.split("[Build-Up]")[2].split("[Drop]")[0].strip().splitlines()
    assert len(second_build) == 1


def test_chant_lanes_get_the_club_cut_and_rap_keeps_its_verses():
    seen = {}
    for i in range(60):
        b = make_brief(P, f"2026-12-{1 + i // 5:02d}" + (f"-{i % 5}" if i % 5 > 1 else ""), [], 0)
        if b["arrangement"] in ("club", "song"):
            seen.setdefault(b["genre_group"], set()).add(b["arrangement"])
            if b["arrangement"] == "club":
                assert "sparse" in b["caption"] and "drops instrumental" in b["caption"]
                assert len(b["caption"]) < 1600   # the club line is shorter than the full song vocals line
    for g in ("hardtech", "psy"):
        if g in seen:
            assert seen[g] == {"club"}, seen
    for g in ("rap", "hiphop"):
        if g in seen:
            assert seen[g] == {"song"}, seen


def test_rap_songs_are_built_like_outrun_your_shadow():
    """Anchit, 2026-11-20: "songs like outrun your shadow with better drops". Every verse stays,
    and there are two drops that are music with one short chant, never two drops in a row."""
    rap = [s for s in songbook.load() if set(s.groups) & {"rap", "hiphop"}]
    assert rap
    for s in rap:
        cut = songbook_club.rap_cut(s)
        tags = re.findall(r"^\[([^\]]+)\]$", cut, re.M)
        assert tags.count("Drop") == 2, (s.title, tags)
        assert not any(a == b == "Drop" for a, b in zip(tags, tags[1:])), (s.title, tags)
        for d in re.findall(r"\[Drop\]\n([^\[]*)", cut):
            assert 1 <= len(d.split()) <= 6, (s.title, d)
        for tag, lines in songbook.sections(s.lyrics):
            if tag.startswith("verse"):
                assert all(ln in cut for ln in lines), (s.title, "a verse line was cut")
