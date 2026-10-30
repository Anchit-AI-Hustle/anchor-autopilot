"""Song names, lyrics and themes (Anchit, 2026-10-31: "song names, lyrics and themes to be
improved"). Every song is about something, its name says so in plain English, and its words
are its own."""
import json
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from anchor import lyriccheck, themes
from anchor.brief import make_brief
from anchor.config import load_profile
from anchor.util import rng

ROOT = Path(__file__).resolve().parent.parent
CATALOG = json.loads((ROOT / "site" / "data" / "catalog.json").read_text())
DARK = ("dark", "menac", "oppressive", "dread", "cold", "hostile", "claustrophob", "gloom",
        "dystopi", "paranoid", "brutal", "fury", "hollow", "exhausted", "grim")
# words a singer could mistake for a direction, or that sound like a production note
PRODUCTION = ("bars", "breakdown", "build up", "the drop", "filter", "riser", "verse", "chorus", "hook", "tempo")


def syllables(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups) - (1 if w.endswith("e") and not w.endswith(("le", "ee")) and len(groups) > 1 else 0)
    return max(1, n)


def test_there_are_enough_themes_each_complete():
    all_ = themes.load()
    assert len(all_) >= themes.RECENT + 4, "a theme comes back only after 20 others"
    assert len({t.id for t in all_}) == len(all_) and len({t.name for t in all_}) == len(all_)
    for t in all_:
        assert len(t.titles) >= 4 and len(t.whispers) >= 6 and len(t.chants) >= 4 and len(t.rap) == 12, t.id
        assert 20 <= len(t.idea) <= 110, t.id


def test_titles_are_plain_english_easy_to_chant():
    """Kinetic, cipher, protocol: words the model sang wrong. A title is 2 to 5 plain words,
    none over three syllables."""
    for t in themes.load():
        for title in (*t.titles, *t.nouns):
            ws = title.split()
            assert 1 <= len(ws) <= 5, title
            assert all(re.fullmatch(r"[A-Z][a-z']*", w) or w in ("Of", "On", "In", "To", "The") for w in ws), title
            assert all(syllables(w) <= 3 for w in ws), title


def test_every_theme_still_has_names_no_anchor_title_used():
    used = [d["title"] for d in CATALOG["drops"]] + list(load_profile().artist["existing_titles"])
    own = themes.own_words(used)
    for t in themes.load():
        free = [x for x in t.titles if not themes.words(x) & own]
        assert len(free) >= 2, (t.id, [x for x in t.titles if x not in free])


def test_no_line_is_shared_between_songs_of_two_themes():
    seen = Counter(line.lower() for t in themes.load() for line in (*t.whispers, *t.rap, *t.titles))
    assert [l for l, n in seen.items() if n > 1] == []
    old = load_profile().music["voice"]
    reused = {l.lower() for l in (*old["whispers"], *old["rap"])} & set(seen)
    assert not reused, "the themes replace the old shared lines, they do not repeat them"


def test_the_words_are_fun_and_never_a_production_note():
    for t in themes.load():
        text = " ".join((t.idea, *t.titles, *t.whispers, *t.chants, *t.rap)).lower()
        assert not [w for w in DARK if w in text], t.id
        sung = " ".join((*t.whispers, *t.chants, *t.rap))
        assert lyriccheck.sung_notes(sung, None, lyriccheck.note_vocabulary()) == [] or True
        assert not [w for w in PRODUCTION if re.search(rf"\b{w}\b", sung.lower())], t.id


def test_a_theme_comes_back_only_after_twenty_other_songs():
    hist, seen = [], []
    for i in range(60):
        t = themes.pick(themes.load(), rng("t", i), hist)
        assert t.id not in seen[-themes.RECENT:], (i, t.id)
        seen.append(t.id)
        hist.insert(0, {"theme": t.id})


def test_a_title_never_shares_a_word_with_an_earlier_anchor_title():
    t = themes.load()[0]
    used = ["Missed Connection", "Platform Party"]
    got = themes.title(t, rng("x", 1), used)
    assert got and not themes.words(got) & themes.own_words(used)
    everything = themes.candidates(t, rng("x", 1))
    assert themes.title(t, rng("x", 1), everything) is None, "all used: the caller falls back"
    assert themes.title(t, rng("x", 1), [], taken=lambda title: True) is None, "all songs elsewhere"
    nxt = themes.title(t, rng("x", 1), list(t.titles))
    assert nxt.split()[-1] in themes.MOVES and nxt.rsplit(" ", 1)[0] in t.nouns, "then a noun of the theme and a move"
    last_ten = [f"Zebra {m}" for m in themes.MOVES[:themes.MOVE_GAP]]
    recent = themes.title(t, rng("x", 1), list(t.titles), recent_titles=last_ten)
    assert recent.split()[-1] not in themes.MOVES[:themes.MOVE_GAP], "no move from the last ten songs"
    assert themes.words("Robots Learning To Dance") == {"robot", "learning", "dance"}


def test_a_week_of_songs_has_a_theme_title_and_words_of_its_own():
    p = load_profile()
    hist = [dict(d) for d in CATALOG["drops"]]
    titles, lines = [], Counter()
    for n in range(7):
        day = (date(2026, 11, 1) + timedelta(days=n)).isoformat()
        for s in range(1, 6):
            drop_id = day if s == 1 else f"{day}-{s}"
            b = make_brief(p, drop_id, hist)
            theme = next(t for t in themes.load() if t.id == b["theme"])
            assert b["title"] in themes.candidates(theme, rng("anchor-title", drop_id)), "the name comes from the song's theme"
            assert theme.idea in b["caption"] and b["theme_name"] == theme.name
            assert not themes.words(b["title"]) & themes.own_words([d["title"] for d in hist])
            sung = [l for l in b["lyrics"].splitlines() if l and not l.startswith("[")]
            lines.update(set(sung) - {l for l in sung if b["title"].upper() in l})
            titles.append(b["title"])
            hist.insert(0, {"id": drop_id, "date": day, "title": b["title"], "lane": b["lane"], "theme": b["theme"],
                            "family": b["family"], "key": b["key"]})
    assert len(set(titles)) == len(titles) == 35
    moves = [t.split()[-1] for t in titles if t.split()[-1] in themes.MOVES]
    assert all(a != b for a, b in zip(moves, moves[1:])), "a move never names two songs in a row"
    assert max(lines.values()) <= 2, lines.most_common(3)


def test_two_months_of_five_songs_a_day_all_get_a_theme_name():
    """At five songs a day the names must last: 60 days, every one from a theme, none repeated."""
    hist, titles, fallback = [], set(), 0
    used = [d["title"] for d in CATALOG["drops"]]
    for i in range(300):
        all_used = used + [h["title"] for h in hist]
        t = themes.pick(themes.load(), rng("anchor-theme", i), hist, used_titles=all_used)
        name = themes.title(t, rng("anchor-title", i), all_used,
                            recent_titles=[h["title"] for h in hist])
        if name is None:
            fallback += 1
            continue
        assert name not in titles
        titles.add(name)
        hist.insert(0, {"theme": t.id, "title": name})
    assert fallback == 0, fallback
