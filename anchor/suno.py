"""Live sync with a public Suno profile.

The public profile page embeds the whole song payload, so the robot can read the
catalogue without an API key: what exists, how long it is, what it was prompted with,
how it is doing. Each song is then rated against the channel's format and marked
postable or not, and the result goes on the website.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone

from .util import log

PROFILE_URL = "https://suno.com/@{handle}"
UA = "Mozilla/5.0 (compatible; anchor-autopilot/1.0; +https://anchor.anchit-tandon.com)"

# what this channel is
ON_FORMAT = ("techno", "industrial", "rawstyle", "hardstyle", "warehouse", "acid",
             "peak time", "peak-time", "hypnotic", "hard dance", "schranz")
OFF_FORMAT = ("hip hop", "rap", "garage", "drum and bass", "dnb", "liquid", "pop",
              "ballad", "acoustic", "lo-fi", "lofi", "country", "jazz", "trance", "house")
PERSONAL = ("ayushi", "birthday", "tauji", "rohit", "i love you", "only you")


def _payload(html: str) -> list[dict]:
    """Pull the clip objects out of the page's embedded data."""
    raw = html.replace('\\"', '"').replace("\\\\", "\\")
    songs, seen = [], set()
    for m in re.finditer(r'"content_type":"clip","content_item":\{', raw):
        start = m.end() - 1
        depth, i = 0, start
        while i < len(raw):                      # walk to the matching brace
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        chunk = raw[start:i + 1]
        try:
            obj = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        sid = obj.get("id")
        if not sid or sid in seen or obj.get("status") != "complete":
            continue
        seen.add(sid)
        media = obj.get("media_urls") or []
        audio = next((u["url"] for u in media if u.get("url", "").endswith(".m4a")), None)
        meta = obj.get("metadata") or {}
        songs.append({
            "id": sid,
            "title": (obj.get("title") or "").strip() or "Untitled",
            "duration_s": round(float(meta.get("duration") or obj.get("duration") or 0), 1),
            "tags": (meta.get("tags") or "").strip(),
            "model": obj.get("major_model_version") or obj.get("model_name") or "",
            "plays": int(obj.get("play_count") or 0),
            "upvotes": int(obj.get("upvote_count") or 0),
            "created_at": obj.get("created_at") or "",
            "image": obj.get("image_large_url") or obj.get("image_url") or "",
            "audio_url": audio,
            "video_url": obj.get("video_url") or "",
            "url": f"https://suno.com/song/{sid}",
        })
    return songs


def fetch(handle: str, timeout: int = 40) -> list[dict]:
    req = urllib.request.Request(PROFILE_URL.format(handle=handle), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        html = r.read().decode("utf-8", "replace")
    songs = _payload(html)
    log(f"suno: {len(songs)} public song(s) on @{handle}")
    return songs


def rate(song: dict) -> dict:
    """Score a song for this channel and decide whether it can be posted.

    Deterministic and explainable: genre against the format, length against the slot,
    the model it was made on, and how it has done on Suno.
    """
    tags = song["tags"].lower()
    title = song["title"].lower()
    dur = song["duration_s"]
    hits = [w for w in ON_FORMAT if w in tags]
    misses = [w for w in OFF_FORMAT if w in tags]
    genre = 4.0 if not hits else min(4.0, 2.2 + 0.45 * len(hits))
    if misses and not hits:
        genre = 0.6
    elif misses:
        genre = max(1.6, genre - 0.9 * len(misses))

    if dur >= 150:
        length, slot = 2.5, "full release"
    elif dur >= 120:
        length, slot = 2.2, "full release"
    elif dur >= 60:
        length, slot = 1.3, "Short only"
    else:
        length, slot = 0.4, "too short"

    model = song["model"].lower()
    fidelity = 1.5 if any(v in model for v in ("v6", "v5")) else (1.2 if "v4.5" in model else 0.7)
    traction = min(1.0, song["plays"] / 40) + min(0.5, song["upvotes"] * 0.25)
    personal = any(p in title for p in PERSONAL)

    score = round(min(10.0, genre + length + fidelity + traction), 1)
    postable = bool(hits and not personal and dur >= 60 and genre >= 2.0)

    if personal:
        why = "personal track — off the channel"
    elif not hits and misses:
        why = f"{misses[0]}, not the hard techno format"
    elif not hits:
        why = "prompt does not say what it is"
    elif dur < 60:
        why = f"{dur:.0f}s — too short to stand as a release"
    elif dur < 150:
        why = f"{dur:.0f}s — works as a Short, thin as a full drop"
    else:
        why = f"on format ({', '.join(hits[:3])}), {dur / 60:.1f} min"

    return {**song, "rating": score, "postable": postable, "slot": slot, "verdict": why}


def catalogue(handle: str) -> dict:
    songs = [rate(s) for s in fetch(handle)]
    songs.sort(key=lambda s: (-s["rating"], -s["duration_s"]))
    return {
        "handle": handle,
        "profile_url": PROFILE_URL.format(handle=handle),
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "total": len(songs),
        "postable": sum(1 for s in songs if s["postable"]),
        "songs": songs,
    }
