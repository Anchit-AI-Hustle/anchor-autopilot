"""Whole songs, written by a songwriter, one per drop (Anchit, 2026-11-07: "the songs need proper
theme selection and lyrics which both need to be thought of properly and structurally and
written as humans ... not every song requires a shloka, not every song should have repeated
flows. Need uniqueness, realness and logic. Choose the song name based on theme and lyrics").

``artist/songbook/*.toml`` holds complete songs: a title taken from the hook, a form (story,
revolt, argument, confession, letter, celebration, vibe, dialogue, mantra), the genre groups it
fits, the human voice that sings it, one line on what it is about, and the full lyric sheet with
ACE-Step section tags. Each song is used once. ``artist/songbook/GUIDE.md`` is how they are
written; the line-pool themes (anchor.themes) are only the fallback when the book runs dry.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import ROOT
from .util import log

SONGBOOK_DIR = ROOT / "artist" / "songbook"
FORMS = ("story", "revolt", "argument", "confession", "letter", "celebration", "vibe", "dialogue", "mantra")
GROUPS = ("hardtech", "psy", "rap", "hiphop")
MAX_LYRICS = 1900
LOW_WATER = 15          # fewer unused songs than this and the run says so (a refill is due)
# words a reader of the guide agreed never to write (artist/songbook/GUIDE.md, "Never")
BANNED = re.compile(r"\b(robots?|machines?|systems?|circuits?|codes?|signals?|data|void|neon|cyber|digital|algorithms?)\b",
                    re.I)
SMALL = 4
# words the caption may not carry (tests/test_profile_titles_brief.py DARK, Anchit 2026-10-04: the
# sound stays bouncy and fun); the lyrics may say them, the about line and the voice may not
DARK = ("dark", "menac", "oppressive", "dread", "cold", "hostile", "claustrophob", "gloom",
        "dystopi", "paranoid", "brutal", "fury", "hollow", "exhausted", "grim")
TAG = re.compile(r"^\[([^\]:,]+?)\s*(?:[:,][^\]]*)?\]\s*$")


def bare_tags(lyrics: str) -> str:
    """Section tags without directions: ACE-Step sings a direction written inside a tag
    ("[Intro: whispered]" came out sung, 2026-10-31), so only the section name stays."""
    out = []
    for line in lyrics.strip().splitlines():
        m = TAG.match(line.strip())
        out.append(f"[{m.group(1).strip()[:13]}]" if m else line.rstrip())
    return "\n".join(out) + "\n"


@dataclass(frozen=True)
class Song:
    id: str
    title: str
    form: str
    groups: tuple[str, ...]
    voice: str
    about: str
    lyrics: str

    def sung_lines(self) -> list[str]:
        return [ln.strip() for ln in self.lyrics.splitlines() if ln.strip() and not ln.strip().startswith("[")]


@lru_cache(maxsize=4)
def load(directory: Path | str = SONGBOOK_DIR) -> tuple[Song, ...]:
    songs = []
    for path in sorted(Path(directory).glob("*.toml")):
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
        for s in raw.get("songs", []):
            songs.append(Song(id=s["id"], title=s["title"], form=s["form"], groups=tuple(s["groups"]),
                              voice=s["voice"], about=s["about"], lyrics=bare_tags(s["lyrics"])))
    return tuple(songs)


def problems(songs: tuple[Song, ...]) -> list[str]:
    """Everything that would make a song unfit to sing; empty when the book is clean."""
    out, ids, titles = [], set(), set()
    for s in songs:
        where = f"{s.id} ({s.title})"
        if s.id in ids:
            out.append(f"{where}: id used twice")
        if s.title.lower() in titles:
            out.append(f"{where}: title used twice")
        ids.add(s.id)
        titles.add(s.title.lower())
        if s.form not in FORMS:
            out.append(f"{where}: unknown form {s.form!r}")
        if not s.groups or any(g not in GROUPS for g in s.groups):
            out.append(f"{where}: groups must be some of {GROUPS}")
        if len(s.lyrics) > MAX_LYRICS:
            out.append(f"{where}: lyrics {len(s.lyrics)} characters, over {MAX_LYRICS}")
        if s.title.lower() not in s.lyrics.lower():
            out.append(f"{where}: the title is never sung")
        if "[drop" not in s.lyrics.lower():
            out.append(f"{where}: no [Drop] section")
        for field in (s.lyrics, s.voice, s.about, s.title):
            if "—" in field or "–" in field:
                out.append(f"{where}: em or en dash")
                break
        m = BANNED.search(s.lyrics)
        if m:
            out.append(f"{where}: banned word {m.group(0)!r}")
        if re.search(r"\b(robotic|vocoder|auto-?tune|text-to-speech|monotone)\b", s.voice, re.I):
            out.append(f"{where}: the voice must be a person")
        hits = [w for w in DARK if w in (s.voice + " " + s.about).lower()]
        if hits:
            out.append(f"{where}: voice or about line says {hits} (the caption stays bouncy)")
        if s.form == "mantra" and "psy" not in s.groups:
            out.append(f"{where}: mantras belong to psy songs only")
    return out


def _words(title: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z']+", title.lower()) if len(w) >= SMALL}


def pick(songs: tuple[Song, ...], group: str, r, history: list[dict], *, used_titles: list[str] = (),
         avoid_titles: tuple[str, ...] = (), taken=None, recent: int = 10, report: dict | None = None) -> Song | None:
    """The next song for a drop of ``group``: never used before (by id or title), not a title the
    singer got wrong on an earlier take, not the same form as the song before it, no word
    shared with the last ``recent`` titles, and not an existing song elsewhere (``taken``).
    ``history`` is newest first. None when the book has nothing left for the group."""
    used_ids = {d.get("theme") for d in history}
    used = {t.lower() for t in used_titles} | {t.lower() for t in avoid_titles}
    recent_words = set().union(*(_words(d.get("title", "")) for d in history[:recent])) if history else set()
    by_id = {s.id: s for s in songs}
    last_form = next((by_id[d["theme"]].form for d in history if d.get("theme") in by_id), None)
    fits = [s for s in songs if group in s.groups and s.id not in used_ids and s.title.lower() not in used]
    if not fits:
        return None
    left = len(fits)
    if left < LOW_WATER:
        log(f"songbook: only {left} unused {group} songs left; write more (artist/songbook/GUIDE.md)")
    order = list(fits)
    r.shuffle(order)
    # best first: a new form and fresh words, then a new form, then anything
    order.sort(key=lambda s: (s.form == last_form, bool(_words(s.title) & recent_words)))
    report = {} if report is None else report
    report.setdefault("rejected", [])
    for s in order:
        verdict = None
        if taken is not None:
            try:
                verdict = taken(s.title)
            except Exception:  # noqa: BLE001 - a lookup outage must not stop the drop
                verdict = None
            report["checked"] = report.get("checked", 0) + 1
            if verdict:
                log(f"songbook: {s.title!r} is already a song elsewhere, skipped")
                report["rejected"].append(s.title)
                continue
        report["verified"] = None if taken is None else verdict is False
        return s
    return None


def find(song_id: str | None) -> Song | None:
    return next((s for s in load() if s.id == song_id), None) if song_id else None


def vocals_line(song: Song) -> str:
    """The caption's vocal layer for this song: the one person who sings it."""
    return f"Vocals: {song.voice}, natural English"
