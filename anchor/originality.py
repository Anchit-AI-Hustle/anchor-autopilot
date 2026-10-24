"""Is a title already a song somewhere? (Anchit, 2026-10-24: no title may match a song that
already exists, "Victory Lap" being the example.)

Three free, key-less catalogues are asked, each covering a different slice of released music:
MusicBrainz (the open music encyclopedia, tens of millions of recordings), the iTunes Search
API (the Apple Music / iTunes store) and the Deezer API (a second big streaming store). A title
is taken when any of them lists a song whose title, with "(feat. ...)", "(Remix)" and similar
suffixes stripped, is the same words as ours.

Each catalogue rate-limits bursts (MusicBrainz asks for one request a second; the iTunes API
answers a burst with 403), so calls are spaced and retried. A catalogue that still does not
answer counts as unknown, never as free: ``taken`` returns None only when none of the three
answered, and the brief records that the title went out unverified.

Tests switch the network off with ANCHOR_TITLE_CHECK=0 (see tests/conftest.py).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

USER_AGENT = "ANCHOR-autopilot/1.0 (https://anchor.anchit-tandon.com)"
_last_call: dict[str, float] = {}
SPACING_S = {"musicbrainz": 1.1, "itunes": 3.1, "deezer": 0.2}


def norm(title: str) -> str:
    """The words of a title: lower case, bracketed and " - " suffixes and feat. credits removed."""
    t = title.lower()
    t = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", t)             # (feat. X), [Remix], (Live)
    t = re.split(r"\s[-\u2013\u2014]\s", t)[0]               # "Title - Radio Edit"
    t = re.split(r"\s(?:feat\.?|ft\.?|featuring)\s", t)[0]
    t = t.replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def _get(source: str, url: str, tries: int = 3) -> dict | None:
    """GET JSON politely: spaced per catalogue, retried with backoff, None when it never answers."""
    for attempt in range(tries):
        wait = _last_call.get(source, 0) + SPACING_S.get(source, 1.0) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[source] = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            time.sleep(2.0 * (attempt + 1))
    return None


def _musicbrainz(title: str, http) -> int | None:
    q = urllib.parse.quote(f'recording:"{title}"')
    d = http("musicbrainz", f"https://musicbrainz.org/ws/2/recording?query={q}&fmt=json&limit=50")
    if d is None or "recordings" not in d:
        return None
    return sum(1 for r in d["recordings"] if norm(r.get("title", "")) == norm(title))


def _itunes(title: str, http) -> int | None:
    q = urllib.parse.urlencode({"term": title, "entity": "song", "limit": 50})
    d = http("itunes", f"https://itunes.apple.com/search?{q}")
    if d is None or "results" not in d:
        return None
    return sum(1 for r in d["results"] if norm(r.get("trackName", "")) == norm(title))


def _deezer(title: str, http) -> int | None:
    q = urllib.parse.quote(f'track:"{title}"')
    d = http("deezer", f"https://api.deezer.com/search?q={q}&limit=50")
    if d is None or "data" not in d:
        return None
    return sum(1 for r in d["data"] if norm(r.get("title", "")) == norm(title))


SOURCES = {"musicbrainz": _musicbrainz, "itunes": _itunes, "deezer": _deezer}


def lookup(title: str, http: Callable = _get) -> dict[str, int | None]:
    """How many released songs each catalogue lists under exactly this title (None = no answer)."""
    out = {}
    for name, fn in SOURCES.items():
        out[name] = fn(title, http)
        if out[name]:          # one hit is enough: the title is taken
            break
    return out


def taken(title: str, http: Callable = _get) -> bool | None:
    """True when any catalogue has a song with this title, False when the ones that answered
    have none, None when no catalogue answered at all."""
    found = lookup(title, http)
    if any(found.values()):
        return True
    if all(v is None for v in found.values()):
        return None
    return False


def enabled() -> bool:
    return (os.environ.get("ANCHOR_TITLE_CHECK") or "1").lower() not in ("0", "off", "false", "no")


def checker() -> Callable[[str], bool | None] | None:
    """The check the brief runs on every candidate title, or None when switched off."""
    return taken if enabled() else None
