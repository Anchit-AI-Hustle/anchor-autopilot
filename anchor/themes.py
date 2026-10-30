"""What a song is about (Anchit, 2026-10-31: "song names, lyrics and themes to be improved").

Every new song gets a theme from artist/themes.toml. The theme gives it a name that means
something ("Missed The Last Train", not "Kinetic Carbon"), the whispers and chants it sings,
twelve rap bars for the rap and hip hop lanes, and one line for the prompt and the description.
A theme comes back only after the last ``RECENT`` songs used others, and a title is never one
whose words an earlier ANCHOR title already used.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .config import ROOT

THEMES_PATH = ROOT / "artist" / "themes.toml"
RECENT = 20                 # a theme is not used again until this many other songs went out
SMALL = 4                   # words shorter than this ("the", "on", "of") never count as shared
# the moves a theme's noun is paired with once its own titles are used. They are what a dance
# track is called anywhere, so they may come back, just not within the last MOVE_GAP songs
MOVES = ("Stomp", "Bounce", "Shuffle", "Groove", "Party", "Jump", "Hop", "Parade", "Boogie", "Wiggle",
         "Shake", "Swing", "Rave", "Disco", "Strut", "Jam", "Twirl", "Skip")
MOVE_GAP = 10
COMMON = {m.lower() for m in MOVES} | {"dance", "club", "night"}


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    idea: str
    titles: tuple[str, ...]
    whispers: tuple[str, ...]
    chants: tuple[str, ...]
    rap: tuple[str, ...]
    nouns: tuple[str, ...] = ()


@lru_cache(maxsize=4)
def load(path: Path | str = THEMES_PATH) -> tuple[Theme, ...]:
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    return tuple(Theme(id=t["id"], name=t["name"], idea=t["idea"], titles=tuple(t["titles"]),
                       whispers=tuple(t["whispers"]), chants=tuple(t["chants"]), rap=tuple(t["rap"]),
                       nouns=tuple(t.get("nouns", ())))
                 for t in raw["theme"])


def words(title: str) -> set[str]:
    """The words of a title that count when two titles are compared: lower case, no
    punctuation, plural s removed, small words dropped."""
    out = set()
    for w in re.findall(r"[a-z']+", title.lower().replace("’", "'")):
        w = w.strip("'")
        if len(w) >= SMALL:
            out.add(w[:-1] if w.endswith("s") and not w.endswith("ss") else w)
    return out


def own_words(titles: list[str]) -> set[str]:
    """Every word ANCHOR titles have used that no later title may use again; the dance moves
    and "dance", "club", "night" are everyone's and do not count."""
    return (set().union(*(words(t) for t in titles)) if titles else set()) - COMMON


def pick(themes: tuple[Theme, ...], r, history: list[dict], recent: int = RECENT,
         used_titles: list[str] | None = None) -> Theme:
    """A theme none of the last ``recent`` songs used (the least recently used one when all
    were); ``history`` is newest first. With ``used_titles``, a theme with no name left is
    passed over while another has one."""
    last = [d.get("theme") for d in history[:recent] if d.get("theme")]
    if used_titles is not None:
        used = own_words(used_titles)
        live = tuple(t for t in themes if any(not words(c) & used for c in (*t.titles, *t.nouns)))
        themes = live or themes
    fresh = [t for t in themes if t.id not in last]
    if fresh:
        return r.choice(fresh)
    return max(themes, key=lambda t: last.index(t.id) if t.id in last else len(last))


def candidates(theme: Theme, r) -> list[str]:
    """The theme's titles in a shuffled order, then each of its nouns with a move."""
    fixed = r.sample(list(theme.titles), k=len(theme.titles))
    nouns = r.sample(list(theme.nouns), k=len(theme.nouns))
    moves = list(MOVES)
    made = []
    for n in nouns:
        for m in r.sample(moves, k=len(moves)):
            made.append(f"{n} {m}")
    return fixed + made


def title(theme: Theme, r, used_titles: list[str], taken: Callable[[str], bool | None] | None = None,
          report: dict | None = None, recent_titles: list[str] | None = None, max_checks: int = 12) -> str | None:
    """A name for a song of ``theme``: one of its titles, or one of its nouns with a move,
    sharing no word with any title ANCHOR used (the moves excepted), no move used in the
    last ``MOVE_GAP`` songs (``recent_titles``, newest first) and, with ``taken``
    (anchor.originality), no song anywhere. None when the theme has nothing left."""
    used = own_words(used_titles)
    exact = {" ".join(t.lower().split()) for t in used_titles}
    recent_moves = set().union(*(words(t) for t in (recent_titles or [])[:MOVE_GAP])) & COMMON if recent_titles else set()
    rejected, checks = [], 0
    for cand in candidates(theme, r):
        w = words(cand)
        if " ".join(cand.lower().split()) in exact or w & used or w & recent_moves:
            continue
        if taken is not None:
            if checks >= max_checks:
                break
            checks += 1
            if taken(cand):
                rejected.append(cand)
                continue
        if report is not None:
            report.update(theme=theme.id, rejected=rejected, checked=checks,
                          verified=None if taken is None else True)
        return cand
    if report is not None:
        report.update(theme=theme.id, rejected=rejected, checked=checks, verified=None)
    return None
