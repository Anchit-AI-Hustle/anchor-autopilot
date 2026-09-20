"""Titles, descriptions and tags that a search can find.

Measured on 2026-09-20 with vidIQ on this channel: the bare title "Pressure Spiral" scored
67/100, "Pressure Spiral — Acid Industrial Techno, 154 BPM | ANCHOR" scored 72. Keyword
demand the same day: "industrial techno" 105k searches/month at competition 18.5 (the
channel's exact lane, and the lowest competition of anything related), "berlin techno" up
54% in 30 days, "peak time techno" up 68%, "hard techno" 318k/month at competition 37.
So every title carries the lane's genre phrase, every description says it again in the first
two lines (the part YouTube shows before "more"), and the hashtags are the three phrases
with the best demand-to-competition ratio.

The title itself comes from the song when the song has one: the most repeated sung line,
if it is a usable phrase, beats a name the generator drew from a word list ("Welcome to
Project Mayhem" x6 is why that track is called Project Mayhem).
"""
from __future__ import annotations

from datetime import datetime, timezone

import collections
import re

from .config import Lane, Profile

STOP = {"yeah", "woo", "oh", "ah", "hey", "la", "na", "the", "and", "you", "i", "it", "to", "a"}
MAX_TITLE = 100


def _norm(line: str) -> str:
    return re.sub(r"[^a-z' ]", "", line.lower()).strip()


LEAD_INS = ("welcome to the", "welcome to", "this is the beat we are", "this is the beat", "this is the",
            "this is", "we are the", "we are", "i said", "i'll", "i will", "it's", "its", "and the", "and",
            "feel the", "we're")
REJECT = {"i said", "you know", "come on", "let's go"}   # sung a lot, says nothing
FILLER = {"yeah", "woo", "oh", "ah", "hey", "la", "na", "uh", "ooh"}


def _clean(hook: str) -> str:
    changed = True
    while changed:
        changed = False
        for lead in LEAD_INS:
            if hook.startswith(lead + " ") and len(hook.split()) - len(lead.split()) >= 2:
                hook = hook[len(lead) + 1:]
                changed = True
    return hook


def hook_title(lyrics: str | None, min_repeats: int = 2, max_words: int = 10) -> str | None:
    """The line the song repeats most, title-cased, or None if nothing qualifies.

    A qualifying hook is sung at least twice and, once its lead-in is stripped ("welcome to",
    "this is the beat we are"), is two to five real words that are not filler shouts.
    "Push it past the limit" qualifies; "Woo" and "I said" do not.
    """
    if not lyrics:
        return None
    counts: collections.Counter = collections.Counter()
    for raw in lyrics.splitlines():
        raw = re.sub(r"\[.*?\]", "", raw)                 # section tags are not lyrics
        for part in re.split(r"[,;.!?]+", raw):
            words = [w for w in _norm(part).split() if w]
            if 2 <= len(words) <= max_words:
                counts[" ".join(words)] += 1
    for hook, c in counts.most_common():
        if c < min_repeats:
            break
        hook = _clean(hook)
        words = hook.split()
        if hook in REJECT or not (2 <= len(words) <= 5) or all(w in STOP | FILLER for w in words):
            continue
        return " ".join(w.capitalize() if i == 0 or w not in {"of", "the", "a", "to", "in", "and"} else w
                        for i, w in enumerate(words))
    return None


def genre_phrase(lane: Lane) -> str:
    """The first phrase of the lane's genre line, Title Case: 'Acid Industrial Techno'."""
    return lane.genre_line.split(",")[0].strip()


def youtube_title(title: str, lane: Lane, bpm: int, artist: str) -> str:
    t = f"{title} — {genre_phrase(lane)}, {int(bpm)} BPM | {artist}"
    if len(t) <= MAX_TITLE:
        return t
    t = f"{title} — {genre_phrase(lane)} | {artist}"
    return t[:MAX_TITLE]


def tags(profile: Profile, lane: Lane, bpm: int) -> list[str]:
    yt = profile.youtube
    return list(dict.fromkeys([*lane.tags, *yt["base_tags"], genre_phrase(lane).lower(),
                               f"{int(bpm)} bpm techno", "techno 2026", "ai techno", "techno full track"]))


def vibe_copy(brief: dict) -> str:
    """Two short lines about the record, in the house voice: what it does, not its specs.

    The mood arc is already written as a sentence in the profile ("tense and coiled, exploding
    at the first drop, never letting go"); the special moment is the one detail worth a line.
    A queued track with hand-written copy (``brief['vibe']``) keeps it.
    """
    if brief.get("vibe"):
        return brief["vibe"]
    mood = (brief.get("mood") or "").strip().rstrip(".")
    special = (brief.get("special") or "").strip().rstrip(".")
    lines = []
    if mood:
        lines.append(mood[0].upper() + mood[1:] + ".")
    if special:
        lines.append(special[0].upper() + special[1:] + ".")
    return "\n\n".join(lines) if lines else f"{brief['title']}. Nothing soft in it."


def description(profile: Profile, brief: dict, platform: str = "youtube") -> str:
    """The copy (hook, body, why, moment, ask) first, because that is what sits above the fold;
    then genre · BPM · artist, the links, the cadence with the AI disclosure, the © line and
    the hashtags. Instagram gets the site instead of the playlist and its own hashtag set."""
    yt, name = profile.youtube, profile.artist["name"]
    lane = profile.lane(brief["lane"])
    site = profile.artist["site_url"].removeprefix("https://").rstrip("/")
    playlist = yt.get("playlist_url", "")
    copy = brief.get("copy") or {}
    body = copy.get("body") or vibe_copy(brief)
    year = (brief.get("date") or datetime.now(timezone.utc).date().isoformat())[:4]
    rights = f"© {year} {name}. All rights reserved."
    cadence = f"A new {name} track every other day. Made with AI music tools and a lot of my own hours; AI use disclosed, always."
    line = f"{genre_phrase(lane)} · {int(brief['bpm'])} BPM · {name}"
    if platform == "instagram":
        tags = " ".join(dict.fromkeys([*yt["hashtags"], *yt.get("instagram_hashtags", [])]))
        return "\n".join([body, "", line, "", f"Full catalogue, free: {site}", "", cadence, rights, "", tags])
    links = [f"Every {name} track, full length: {playlist}" if playlist else f"Full catalogue: {site}",
             f"Listen and download free: {site}"]
    handle = profile.artist.get("instagram_handle")
    if handle:
        links.append(f"Instagram: @{handle.lstrip('@')}")
    tags = copy.get("hashtags") or " ".join(yt["hashtags"])
    return "\n".join([body, "", line, "", *links, "", cadence, rights, "", tags])
