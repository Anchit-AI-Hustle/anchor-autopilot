"""The songbook (Anchit, 2026-11-07): whole human songs, each used once, named by their hook."""
import random
from datetime import date, timedelta

from anchor import songbook
from anchor.brief import make_brief
from anchor.config import load_profile


def test_the_book_is_clean():
    songs = songbook.load()
    assert songbook.problems(songs) == []
    for g in songbook.GROUPS:
        assert sum(g in s.groups for s in songs) >= 8, g


def test_mantras_are_rare_and_only_psy():
    songs = songbook.load()
    psy = [s for s in songs if "psy" in s.groups]
    mantras = [s for s in songs if s.form == "mantra"]
    assert all("psy" in s.groups for s in mantras)
    assert len(mantras) * 4 <= len(psy)          # not every song is a shloka
    import re
    shloka = re.compile(r"\b(om|asato|purnam\w*|savitur|shanti|namah|mantra|shloka)\b", re.I)
    assert [s.title for s in songs if s.form != "mantra" and shloka.search(s.lyrics)] == []


def test_forms_vary():
    songs = songbook.load()
    assert len({s.form for s in songs}) >= 8
    assert len({s.voice for s in songs}) == len(songs)          # every song its own singer


def test_a_month_of_drops_never_repeats_a_song_or_a_form_back_to_back():
    songs = songbook.load()
    history: list[dict] = []
    groups = ["hardtech", "psy", "rap", "hiphop"]
    for i in range(36):
        g = groups[i % 4]
        s = songbook.pick(songs, g, random.Random(i), history, used_titles=[d["title"] for d in history])
        if s is None:
            break
        assert s.id not in {d["theme"] for d in history}
        if history:
            prev = songbook.find(history[0]["theme"])
            others = [x for x in songs if g in x.groups and x.id not in {d["theme"] for d in history}
                      and x.form != prev.form]
            if others:
                assert s.form != prev.form
        history.insert(0, {"theme": s.id, "title": s.title})
    assert len(history) >= 30


def test_a_misheard_title_moves_to_another_song():
    songs = songbook.load()
    first = songbook.pick(songs, "rap", random.Random(1), [])
    second = songbook.pick(songs, "rap", random.Random(1), [], avoid_titles=(first.title,))
    assert second is not None and second.id != first.id


def test_the_brief_sings_a_whole_songbook_song():
    p = load_profile()
    seen = []
    start = date(2026, 11, 8)
    history: list[dict] = []
    for i in range(6):
        b = make_brief(p, (start + timedelta(days=i)).isoformat(), history)
        song = songbook.find(b["theme"])
        assert song is not None, b["theme"]
        assert b["title"] == song.title and b["lyrics"] == song.lyrics
        assert f"Vocals: {song.voice}" in b["caption"]
        assert b["form"] == song.form and b["title"].lower() in b["lyrics"].lower()
        assert song.id not in seen
        seen.append(song.id)
        history.insert(0, {"id": b["id"], "date": b["date"], "title": b["title"], "lane": b["lane"],
                           "theme": b["theme"], "family": b["family"], "key": b["key"]})


def test_tags_are_bare_so_no_direction_gets_sung():
    for s in songbook.load():
        for line in s.lyrics.splitlines():
            if line.startswith("["):
                assert ":" not in line and "," not in line and len(line) < 16, (s.title, line)
