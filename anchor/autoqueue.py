"""Your own Suno songs go out first, on their own.

There is no official Suno API (checked 2026-09-23), and the third-party "Suno APIs" drive
accounts through the web app against Suno's terms, so the robot never generates on Suno.
What it does instead: every day, before it renders anything, it reads your public Suno
profile and queues the best song that is not out yet, provided it is on format, above the
rating floor, not another take of a song already released, and not one of the songs you
keep for yourself (``[queue] never_words`` / ``never_titles``: birthdays, family, anything
personal). Lyria renders a new record only on a day the queue is empty.

Every decision is written down (``decide``), so the site and ``anchor queue-plan`` can show
why a song went out, waits, or stays home.
"""
from __future__ import annotations

from pathlib import Path

from .config import Profile
from .util import log

DEFAULT_NEVER_WORDS = ("birthday", "happy birthday", "anniversary", "wedding", "mom", "mum", "mummy", "dad", "papa",
                       "father", "mother", "sister", "brother", "family", "my love", "wife", "husband", "girlfriend",
                       "boyfriend", "baby girl", "baby boy", "valentine", "proposal")


def settings(profile: Profile) -> dict:
    q = dict(profile.raw.get("queue") or {})
    q.setdefault("auto", True)
    q.setdefault("min_rating", 6.0)
    q.setdefault("never_words", list(DEFAULT_NEVER_WORDS))
    q.setdefault("never_titles", [])
    return q


def _personal(song: dict, q: dict) -> str | None:
    hay = " ".join([song.get("title") or "", song.get("tags") or ""]).lower()
    for t in q["never_titles"]:
        if t.lower() == (song.get("title") or "").lower():
            return f"kept private: title on the never list ({t!r})"
    for w in q["never_words"]:
        if w.lower() in hay:
            return f"kept private: {w!r} in the title or prompt"
    return None


def decide(song: dict, profile: Profile, *, released_ids: dict, posted_ideas: set, queued_ids: set,
           released_groups: set, queued_ideas: set = frozenset(), queued_groups: set = frozenset()) -> dict:
    """One song, one verdict: 'released', 'queued', 'eligible' or 'held', with the reason."""
    from .suno import title_key
    q = settings(profile)
    sid = song["id"]
    if sid in released_ids:
        when = released_ids[sid]
        return {"verdict": "released", "reason": f"released {when[:10]}" if when and when[0].isdigit() else "released (on the site)"}
    queued = sid in queued_ids
    tail = " (it is in the queue, and the guard will skip it)" if queued else ""
    why = _personal(song, q)
    if why:
        return {"verdict": "held", "reason": why}
    if not song.get("postable"):
        return {"verdict": "held", "reason": f"not on format: {song.get('verdict') or 'fails the format checks'}"}
    if float(song.get("rating") or 0) < float(q["min_rating"]):
        return {"verdict": "held", "reason": f"rated {song.get('rating')} under the {q['min_rating']} floor"}
    key = title_key(song.get("title") or "")
    if key and key in posted_ideas and not song.get("_force"):
        return {"verdict": "held", "reason": "another take of a song already on the channel (same title idea); queue-add --force to release it anyway" + tail}
    if song.get("group") and song["group"] in released_groups and not song.get("_force"):
        return {"verdict": "held", "reason": "same prompt batch as a song already on the channel; queue-add --force to release it anyway" + tail}
    if queued:
        return {"verdict": "queued", "reason": "waiting in the queue, goes out next"}
    if (key and key in queued_ideas) or (song.get("group") and song["group"] in queued_groups):
        return {"verdict": "held", "reason": "another take of a song waiting in the queue"}
    return {"verdict": "eligible", "reason": f"on format, rated {song.get('rating')}, a song the channel does not have"}


def plan(profile: Profile, songs: list[dict], queue_dir: Path | None = None, catalog_path: Path | None = None) -> list[dict]:
    from . import queue as qmod
    released_ids = qmod.released(queue_dir)
    posted = qmod.posted_ideas(catalog_path)
    meta = qmod.read_json((Path(queue_dir) if queue_dir else qmod.QUEUE) / "queue.json", {}) or {}
    queued_ids = {e.get("suno_id") for e in meta.values() if e.get("suno_id") and not e.get("released_at")}
    forced = {e.get("suno_id") for e in meta.values() if e.get("force") and not e.get("released_at")}
    songs = [{**s, "_force": s["id"] in forced} for s in songs]
    released_groups = {s.get("group") for s in songs if s.get("group") and s["id"] in released_ids}
    # a song waiting in the queue holds its own twins back too, so no two takes ever line up
    from .suno import title_key
    queued_ideas = {title_key(s.get("title") or "") for s in songs if s["id"] in queued_ids}
    queued_groups = {s.get("group") for s in songs if s.get("group") and s["id"] in queued_ids}
    out = []
    for s in sorted(songs, key=lambda s: -(s.get("rating") or 0)):
        d = decide(s, profile, released_ids=released_ids, posted_ideas=posted, queued_ids=queued_ids, released_groups=released_groups,
                   queued_ideas=queued_ideas, queued_groups=queued_groups)
        out.append({"id": s["id"], "title": s.get("title"), "rating": s.get("rating"), "duration_s": s.get("duration_s"), **d})
    return out


def fill(profile: Profile, songs: list[dict], queue_dir: Path, catalog_path: Path | None = None) -> dict | None:
    """Queue the best eligible song, if the queue has nothing waiting. Returns the entry or None."""
    from . import queue as qmod
    from .suno import queue_entry
    if not settings(profile)["auto"]:
        return None
    if qmod.pending(queue_dir) or qmod.reserved(queue_dir):
        return None
    for row in plan(profile, songs, queue_dir, catalog_path):
        if row["verdict"] == "eligible":
            song = next(s for s in songs if s["id"] == row["id"])
            res = queue_entry(song, queue_dir)
            log(f"autoqueue: {song['title']!r} (rated {song.get('rating')}) goes out next")
            return res["entry"]
    log("autoqueue: nothing eligible on Suno; the engine renders today")
    return None
