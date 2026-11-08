"""The Sync with Suno page (anchor.anchit-tandon.com/suno/): every song on the channel's Suno
profile as a checklist, each with what would be posted, and one button that queues the ticked
ones for YouTube with the choices made on the page.

Anchit, 2026-11-09: "ensure all songs in suno are fetched and shown to me as a checklist ... to
choose which to directly add on single click with all details available in preview already to
youtube - ensure option to create videos over there itself exactly like this - lyrical + motion
+ 3d or lyrical + cinematic ... all options for all features, editing, hashtag with all
already-created-field-inputs ... duplicacy check, preview and listen to song and video".

The page never holds a key: its button opens a prefilled GitHub issue carrying a JSON block
(``FORM_MARK``), and the Queue a Suno song workflow (owner-only) turns it into queue entries.
``defaults`` fills each song's fields with exactly what the robot would post, so an untouched
field changes nothing.
"""
from __future__ import annotations

import json
import re
from datetime import date

from .config import Profile

FORM_MARK = "anchor-suno-sync"
STYLES = {"motion": "Lyrical + motion + 3D", "cinematic": "Lyrical + cinematic"}
BPM_RE = re.compile(r"(\d{2,3})\s*(?:-\s*\d{2,3}\s*)?bpm", re.IGNORECASE)


def guess_lane(profile: Profile, tags: str) -> str:
    """The active lane whose genre words the Suno style prompt names most (hard techno by default)."""
    text = (tags or "").lower()
    best, score = None, 0
    for lane in profile.active_lanes:
        phrases = [p.strip().lower() for p in lane.genre_line.split(",") if p.strip()]
        hit = sum(2 if i == 0 else 1 for i, p in enumerate(phrases)
                  if re.search(rf"(?<![a-z]){re.escape(p)}(?![a-z])", text))
        if hit > score:
            best, score = lane, hit
    return (best or next(l for l in profile.active_lanes if l.group == "hardtech")).id


def guess_bpm(profile: Profile, tags: str, lane_id: str) -> int:
    m = BPM_RE.search(tags or "")
    if m and 60 <= int(m.group(1)) <= 220:
        return int(m.group(1))
    lo, hi = profile.lane(lane_id).bpm
    return (lo + hi) // 2


def defaults(profile: Profile, song: dict) -> dict:
    """What the robot would post for this song, field by field, for the page to show and edit."""
    from .brief import describe
    lane = guess_lane(profile, song.get("tags", ""))
    bpm = guess_bpm(profile, song.get("tags", ""), lane)
    brief = {"title": song["title"], "lane": lane, "bpm": bpm, "date": date.today().isoformat()}
    d = describe(profile, brief)
    tags_line = d["description"].rstrip().rsplit("\n", 1)[-1]
    return {"lane": lane, "lane_name": profile.lane(lane).name, "bpm": bpm,
            "youtube_title": d["youtube_title"], "description": d["description"],
            "hashtags": tags_line if tags_line.startswith("#") else "",
            "style": "motion"}


def parse_form(text: str) -> list[dict]:
    """The ticked songs from an issue body: the fenced JSON block the page writes."""
    for block in re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", re.DOTALL):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if data.get("form") == FORM_MARK:
            out = []
            for s in data.get("songs") or []:
                if not isinstance(s, dict) or not s.get("id"):
                    continue
                style = s.get("style") if s.get("style") in STYLES else "motion"
                out.append({"id": str(s["id"]), "style": style,
                            "title": str(s.get("title") or "").strip()[:100],
                            "youtube_title": str(s.get("youtube_title") or "").strip()[:100],
                            "description": str(s.get("description") or "").strip()[:4900],
                            "hashtags": str(s.get("hashtags") or "").strip()[:500],
                            "lane": str(s.get("lane") or ""),
                            "force": bool(s.get("force"))})
            return out
    return []


def queue_selection(profile: Profile, handle: str, picks: list[dict], queue_dir) -> list[dict]:
    """Queue every ticked song with its choices. A song already released is skipped unless the page
    said release it anyway (``force``); the audio gate still runs at release."""
    from . import suno
    done = []
    for pick in picks:
        song = suno.find(handle, pick["id"])
        if song.get("released_at") and not pick["force"]:
            done.append({"id": song["id"], "title": song["title"], "skipped": "already released"})
            continue
        res = suno.queue_entry(song, queue_dir, force=pick["force"])
        name = res["name"]
        index = queue_dir / "queue.json"
        meta = json.loads(index.read_text())
        e = meta[name]
        e["title"] = pick["title"] or song["title"]
        e["keep_title"] = True                       # his own name for his own song
        e["style"] = pick["style"]
        if song.get("lyrics"):
            e["lyrics"] = song["lyrics"]
        lane = pick["lane"] if pick["lane"] in {l.id for l in profile.lanes} else ""
        if lane:
            e["lane"] = lane
        e["overrides"] = {k: pick[k] for k in ("youtube_title", "description", "hashtags") if pick[k]}
        e["from"] = "sync-with-suno"
        index.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
        done.append({"id": song["id"], "title": e["title"], "queued": name, "style": STYLES[pick["style"]]})
    return done
