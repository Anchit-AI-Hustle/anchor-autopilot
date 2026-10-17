"""Every upload on the channel carries the search phrase, whoever made it.

``retitle`` reads the channel through the Data API, works out each video's genre phrase and
tempo (robot drops from the catalog, the hand uploads from site/data/channel.json), and
rewrites the title to 'Name | Genre | ANCHOR' and the description to open with the
search line. It changes only what differs, so running it every week costs nothing when the
channel is already right, and a title edited by hand into the same form is left alone.
"""
from __future__ import annotations

import re
from pathlib import Path

from .config import CATALOG_PATH, Profile
from .ledger import clean_title
from .seo import MAX_TITLE
from .util import log, read_json
from .youtube import YouTube

CHANNEL_PATH = CATALOG_PATH.parent / "channel.json"
GENRE_LINE = re.compile(r"^.+ · (\d+ BPM · )?[A-Z]+$")          # the old 'Genre · 154 BPM · ANCHOR' footer line
SEARCH_LINE = re.compile(r"^.+?(?: at \d+ BPM)?\. An [A-Z]+ original, free download below\.$")


def search_title(name: str, genre: str, bpm: int | None, artist: str) -> str:
    out = f"{name} | {genre} | {artist}"          # no tempo on any listener surface (2026-10-17)
    return out if len(out) <= MAX_TITLE else name[:MAX_TITLE]


def search_line(genre: str, bpm: int | None, artist: str) -> str:
    return f"{genre}. An {artist} original, free download below."


def rewrite_description(text: str, genre: str, bpm: int | None, artist: str) -> str:
    """The search line first; the old footer genre line gone; everything else untouched."""
    lines = [l for l in text.split("\n") if not GENRE_LINE.match(l.strip())]
    if lines and SEARCH_LINE.match(lines[0].strip()):
        lines = lines[1:]
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return search_line(genre, bpm, artist) + ("\n\n" + body if body else "")


TEMPO_TITLE = re.compile(r"^(?P<name>.+?) \| (?P<genre>.+?) \d{2,3} BPM \| (?P<artist>.+)$")
TEMPO_WORDS = re.compile(r"\s*(?:[·|,-]\s*)?\b\d{2,3} BPM\b", re.I)


def strip_tempo(video: dict) -> tuple[str, str] | None:
    """For a video the records do not know (a hand upload, a full video made before the catalogue kept its id):
    take the tempo out of the words it already has. None when there is no tempo to take out."""
    m = TEMPO_TITLE.match(video["title"])
    title = f"{m['name']} | {m['genre']} | {m['artist']}" if m else TEMPO_WORDS.sub("", video["title"]).strip()
    lines = [re.sub(r" at \d{2,3} BPM(?=\. An )", "", l) if SEARCH_LINE.match(l.strip()) else l
             for l in video["description"].split("\n")]
    desc = "\n".join(re.sub(r"( · )\d{2,3} BPM · ", r"\1", l) for l in lines)
    if title == video["title"] and desc == video["description"]:
        return None
    return title[:MAX_TITLE], desc


def facts(profile: Profile, video: dict, catalog: dict, channel: dict) -> tuple[str, str, int | None] | None:
    """(name, genre phrase, bpm) for a video, or None when nothing on record knows it."""
    known = channel.get("videos", {}).get(video["id"])
    if known:
        return clean_title(known["title"]), known["genre"], known.get("bpm")
    by_url = {}
    for d in catalog.get("drops", []):
        for k in ("youtube_url", "youtube_short_url", "youtube_full_url"):
            u = d.get(k) or ""
            vid = u.rsplit("=", 1)[-1].rsplit("/", 1)[-1] if u else None
            if vid:
                by_url[vid] = d
    d = by_url.get(video["id"])
    if not d:
        return None
    lane = next((l for l in profile.lanes if l.id == d.get("lane")), None)
    genre = lane.genre_line.split(",")[0].strip() if lane else (d.get("lane_name") or "Hard Techno")
    return clean_title(d["title"]), genre, int(d["bpm"]) if d.get("bpm") else None


def run(profile: Profile, *, catalog_path: Path = CATALOG_PATH, channel_path: Path = CHANNEL_PATH,
        api: YouTube | None = None, dry_run: bool = False) -> dict:
    api = api or YouTube()
    catalog = read_json(catalog_path, {}) or {}
    channel = read_json(channel_path, {}) or {}
    artist = profile.artist["name"]
    videos = api.channel_videos(profile.artist["youtube_channel_id"])
    changed, same, unknown = [], [], []
    for v in videos:
        f = facts(profile, v, catalog, channel)
        if not f:
            fallback = strip_tempo(v)
            if not fallback:
                unknown.append(v["id"])
                continue
            title, desc = fallback
            if not dry_run:
                api.update_video(v, title=title, description=desc)
            changed.append({"id": v["id"], "from": v["title"], "to": title})
            continue
        name, genre, bpm = f
        title = search_title(name, genre, bpm, artist)
        desc = rewrite_description(v["description"], genre, bpm, artist)
        if title == v["title"] and desc == v["description"]:
            same.append(v["id"])
            continue
        if not dry_run:
            api.update_video(v, title=title, description=desc)
        changed.append({"id": v["id"], "from": v["title"], "to": title})
    log(f"retitle: {len(changed)} updated, {len(same)} already right, {len(unknown)} unknown{' (dry run)' if dry_run else ''}")
    return {"changed": changed, "same": same, "unknown": unknown}
