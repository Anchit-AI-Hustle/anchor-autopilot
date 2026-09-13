"""Live sync with a public Suno profile.

The public profile page embeds the whole song payload, so the robot can read the
catalogue without an API key: what exists, how long it is, what it was prompted with,
how it is doing. Each song is then rated against the channel's format and marked
postable or not, and the result goes on the website.
"""
from __future__ import annotations

import json
import re
import subprocess
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


def _mmss(s: float) -> str:
    return f"{int(s) // 60}:{int(s) % 60:02d}"


def rate(song: dict) -> dict:
    """Score a song for this channel and show the whole working.

    Nothing here is a black box: four factors make the rating, four checks make the
    yes/no, and every one of them carries the sentence that explains it. The website
    prints all of it, so a No can be argued with and a Yes can be trusted.
    """
    tags = song["tags"].lower()
    title = song["title"].lower()
    dur = song["duration_s"]
    hits = [w for w in ON_FORMAT if w in tags]
    misses = [w for w in OFF_FORMAT if w in tags]

    # 1. genre --------------------------------------------------------------
    genre = 4.0 if not hits else min(4.0, 2.2 + 0.45 * len(hits))
    if misses and not hits:
        genre = 0.6
        gnote = f"prompt asks for {', '.join(misses[:3])} — a different channel"
    elif misses:
        genre = max(1.6, genre - 0.9 * len(misses))
        gnote = (f"{', '.join(hits[:3])}, but also {', '.join(misses[:2])} — "
                 f"the off-format tags cost it {0.9 * len(misses):.1f}")
    elif not hits:
        genre = 4.0
        gnote = "the prompt never says what the genre is, so nothing contradicts the format"
    else:
        gnote = f"prompt names {', '.join(hits[:4])} — straight down the middle of the channel"

    # 2. length -------------------------------------------------------------
    if dur >= 150:
        length, slot = 2.5, "full release"
        lnote = f"{_mmss(dur)} — full release length"
    elif dur >= 120:
        length, slot = 2.2, "full release"
        lnote = f"{_mmss(dur)} — just long enough for a full release"
    elif dur >= 60:
        length, slot = 1.3, "Short only"
        lnote = f"{_mmss(dur)} — carries a Short, thin as a full drop"
    else:
        length, slot = 0.4, "too short"
        lnote = f"{_mmss(dur)} — too short to stand as a release"

    # 3. model --------------------------------------------------------------
    model = song["model"].lower()
    if any(v in model for v in ("v6", "v5")):
        fidelity, fnote = 1.5, f"made on Suno {song['model']} — current generation, cleanest master"
    elif "v4.5" in model:
        fidelity, fnote = 1.2, f"made on Suno {song['model']} — good, half a point behind v5"
    else:
        fidelity, fnote = 0.7, f"made on Suno {song['model'] or 'an older model'} — audible quality gap"

    # 4. traction -----------------------------------------------------------
    traction = min(1.0, song["plays"] / 40) + min(0.5, song["upvotes"] * 0.25)
    tnote = (f"{song['plays']} play{'s' if song['plays'] != 1 else ''} and "
             f"{song['upvotes']} upvote{'s' if song['upvotes'] != 1 else ''} on Suno"
             + (" — no signal yet" if not song["plays"] else ""))

    personal = [p for p in PERSONAL if p in title]
    score = round(min(10.0, genre + length + fidelity + traction), 1)

    factors = [
        {"name": "Genre fit", "score": round(genre, 1), "max": 4.0, "note": gnote},
        {"name": "Length", "score": round(length, 1), "max": 2.5, "note": lnote},
        {"name": "Model", "score": round(fidelity, 1), "max": 1.5, "note": fnote},
        {"name": "Traction", "score": round(traction, 1), "max": 1.5, "note": tnote},
    ]

    checks = [
        {"ok": bool(hits), "label": "On the channel's format",
         "detail": (f"the prompt names {', '.join(hits[:4])}" if hits
                    else "nothing in the prompt says hard techno, industrial, rawstyle or warehouse")},
        {"ok": not personal, "label": "Not a personal track",
         "detail": (f"the title says {personal[0]!r} — that one is yours, not the channel's"
                    if personal else "nothing personal in the title")},
        {"ok": dur >= 60, "label": "Long enough to release",
         "detail": f"{_mmss(dur)} against a 1:00 floor — {slot}"},
        {"ok": genre >= 2.0, "label": "Genre score clears the bar",
         "detail": f"{genre:.1f} against a 2.0 floor"
                   + (f", pulled down by {', '.join(misses[:2])}" if misses else "")},
    ]
    postable = all(c["ok"] for c in checks)
    failed = [c for c in checks if not c["ok"]]

    if failed:
        why = failed[0]["detail"]
    elif dur < 150:
        why = f"on format ({', '.join(hits[:3])}), {_mmss(dur)} — good for a Short"
    else:
        why = f"on format ({', '.join(hits[:3])}), {_mmss(dur)}"

    summary = (f"Rated {score}/10. " + ("Postable: " if postable else "Not yet: ")
               + ("; ".join(c["detail"] for c in failed) if failed
                  else f"{gnote}. {lnote}. {fnote}."))

    return {**song, "rating": score, "postable": postable, "slot": slot, "verdict": why,
            "factors": factors, "checks": checks, "summary": summary}


def catalogue(handle: str) -> dict:
    songs = [rate(s) for s in fetch(handle)]
    songs.sort(key=lambda s: (-s["rating"], -s["duration_s"]))
    annotate_similar(songs)
    families = len({s["group"] for s in songs if s["group"]})
    twins = sum(1 for s in songs if s["group_size"] > 1)
    log(f"suno: {twins} song(s) in {families} near-duplicate family(ies)")
    return {
        "handle": handle,
        "profile_url": PROFILE_URL.format(handle=handle),
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "total": len(songs),
        "postable": sum(1 for s in songs if s["postable"]),
        "families": families,
        "twins": twins,
        "fresh": sum(1 for s in songs if s["postable"] and s["group_pick"]),
        "songs": songs,
    }


# ------------------------------------------------------------------ similarity
STOP = {"the", "a", "an", "and", "of", "with", "for", "to", "in", "on", "part",
        "feat", "remix", "version", "mix", "edit", "bpm", "more", "very"}
NUM = re.compile(r"^\d+([–-]\d+)?$")


def _tokens(text: str) -> set[str]:
    words = re.split(r"[^a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in STOP and not NUM.match(w)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(a: dict, b: dict) -> float:
    """How alike two songs are, 0-1.

    Weighted so the prompt dominates — two tracks built from the same tags are the
    same idea twice even when the titles differ — with the title and the runtime as
    tie-breakers. Deterministic, no model, so the number on the site is reproducible.
    """
    tag = _jaccard(_tokens(a["tags"]), _tokens(b["tags"]))
    ttl = _jaccard(_tokens(a["title"]), _tokens(b["title"]))
    da, db = a["duration_s"], b["duration_s"]
    dur = 1.0 - min(1.0, abs(da - db) / max(60.0, max(da, db))) if da and db else 0.0
    return round(0.62 * tag + 0.28 * ttl + 0.10 * dur, 3)


NEAR = 0.55          # "these two are the same idea"


def title_key(title: str) -> frozenset[str]:
    """What the title is *about*, with take markers stripped.

    "Project Mayhem", "Project Mayhem Part 1" and "Project Mayhem Part 2" all reduce to
    {mayhem, project}: three takes at one idea, however differently they were prompted.
    """
    return frozenset(_tokens(title))


def annotate_similar(songs: list[dict], near: float = NEAR, top: int = 3) -> list[dict]:
    """Attach each song's closest neighbours and group the twins together.

    Groups are transitive (A~B, B~C puts all three in one group) and the highest
    rated song in a group is marked the pick, so the robot posts one of a family
    rather than four near-identical drops in a week.
    """
    for s in songs:
        s["similar"], s["group"], s["group_size"], s["group_pick"] = [], None, 1, True
    pairs = []
    for i, a in enumerate(songs):
        for b in songs[i + 1:]:
            sc = similarity(a, b)
            # Same title = same idea, even when the two takes were prompted in completely
            # different words. Without this, four "Project Mayhem" takes split into two
            # families and two different rows each claimed to be the best one.
            same_title = bool(title_key(a["title"])) and title_key(a["title"]) == title_key(b["title"])
            if sc >= near or same_title:
                pairs.append((sc, a, b))
    for sc, a, b in sorted(pairs, key=lambda p: -p[0]):
        a["similar"].append({"id": b["id"], "title": b["title"], "score": sc})
        b["similar"].append({"id": a["id"], "title": a["title"], "score": sc})

    parent: dict[str, str] = {s["id"]: s["id"] for s in songs}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _, a, b in pairs:                                  # union the twins
        ra, rb = find(a["id"]), find(b["id"])
        if ra != rb:
            parent[ra] = rb

    groups: dict[str, list[dict]] = {}
    for s in songs:
        s["similar"] = sorted(s["similar"], key=lambda x: -x["score"])[:top]
        groups.setdefault(find(s["id"]), []).append(s)
    for root, members in groups.items():
        if len(members) < 2:
            continue
        best = max(members, key=lambda s: (s["rating"], s["duration_s"]))
        for s in members:
            s["group"] = root
            s["group_size"] = len(members)
            s["group_pick"] = s is best
    return songs


# ---------------------------------------------------------------- queue a song
ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def song_id(text: str) -> str:
    """The Suno id out of an id, a song URL or a pasted issue body."""
    m = ID_RE.search(text or "")
    if not m:
        raise ValueError(f"no Suno song id in {text!r}")
    return m.group(0).lower()


def find(handle: str, sid: str) -> dict:
    sid = song_id(sid)
    cat = catalogue(handle)
    for s in cat["songs"]:
        if s["id"] == sid:
            return s
    raise LookupError(f"{sid} is not a public song on @{handle}")


def _fetch(url: str, dest, timeout: int = 180) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 16):
            f.write(chunk)
    return dest.stat().st_size


def _audio_seconds(path) -> float:
    """Seconds of decodable audio in a file, or 0.0. Guards against queueing junk."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True)
    if out.returncode != 0:
        return 0.0
    for token in reversed(out.stdout.split()):
        try:
            return float(token)
        except ValueError:
            continue
    return 0.0


def queue_entry(song: dict, queue_dir) -> dict:
    """Reserve a slot in the release queue without downloading anything yet.

    Only the reference is stored, so the queue stays a few kB of JSON in git instead of
    megabytes of audio. The daily run materialises the file from Suno when it needs it.
    """
    from pathlib import Path
    queue_dir = Path(queue_dir)
    queue_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-z0-9]+", "-", song["title"].lower()).strip("-") or "track"
    # The queue releases files in name order, so lead with the rating inverted: the best
    # song goes out first. queue._title_from strips the prefix back off for the title.
    rank = max(1, min(99, round(100 - float(song["rating"]) * 10)))
    name = f"{rank:02d}-{safe}-{song['id'][:8]}.m4a"

    index = queue_dir / "queue.json"
    meta = json.loads(index.read_text()) if index.exists() else {}
    meta[name] = {
        "title": song["title"],
        "tags": song["tags"],
        "source": "suno",
        "suno_id": song["id"],
        "suno_url": song["url"],
        "video_url": song.get("video_url", ""),
        "rating": song["rating"],
        "duration_s": song["duration_s"],
        "queued_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    index.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    log(f"suno: queued {song['title']!r} as {name} (rated {song['rating']})")
    return {"name": name, "entry": meta[name]}


def materialise(name: str, entry: dict, queue_dir, timeout: int = 180):
    """Fetch a queued song's audio so the pipeline has a real file to release."""
    from pathlib import Path
    dest = Path(queue_dir) / name
    if dest.exists():
        return dest
    video = entry.get("video_url") or ""
    if not video and entry.get("suno_id"):
        video = f"https://cdn1.suno.ai/{entry['suno_id']}.mp4"
    if not video:
        raise ValueError(f"{name} has no source to fetch — put the audio in queue/ by hand")
    tmp = dest.with_suffix(".src.mp4")
    try:
        size = _fetch(video, tmp, timeout)
        if size < 50_000:
            raise OSError(f"download was only {size} bytes - the CDN link may have expired")
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp),
                            "-vn", "-c:a", "copy", str(dest)], capture_output=True, text=True)
        if r.returncode != 0:
            raise OSError(f"could not read the Suno render: {r.stderr.strip()[:200]}")
    finally:
        tmp.unlink(missing_ok=True)
    heard = _audio_seconds(dest)
    if heard < 20:
        dest.unlink(missing_ok=True)
        raise OSError(f"only {heard:.0f}s of audio came through - not releasing a broken file")
    log(f"suno: fetched {entry.get('title', name)!r} ({dest.stat().st_size / 1e6:.1f} MB, {heard:.0f}s)")
    return dest
