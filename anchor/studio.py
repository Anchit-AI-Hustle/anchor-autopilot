"""The Music Studio: a song from a prompt, made exactly the way ANCHOR makes a drop.

Anchit, 2026-11-20: "Music studio in jarvis must use this exact architecture and logics to
create music based on the prompts given". Jarvis (The Third Eye, /tools/music) sends a request
and this module turns it into an ANCHOR brief and runs the same pipeline as a daily drop:

  prompt -> lane (the decided genres, anchor/genres.py classify) -> brief (make_brief: the
  lane's caption, palette, groove, BPM, key, shape, vocals line; the club cut for the chant
  lanes, full verses for rap and hip hop) -> ACE-Step 1.5 on the Mac GPU, several takes ->
  each take: tempo brought up to the lane (to_tempo), quality gate, uniqueness against every
  released song, lyric check (Whisper: no sung production notes, the title in standard
  English), master, song gate -> the best passing take, mastered, as MP3 and FLAC.

What a drop adds after that (cover, videos, release, YouTube) is not done here. A request
that no take passes is held, with the reasons, exactly like a drop.

The request (JSON):
  {"id": "abc123", "prompt": "a rave song about ...", "title": "...", "lyrics": "[Verse 1]...",
   "genre": "acidpsy" or "Acid Psychedelic Techno" or "", "bpm": 170, "duration_s": 210,
   "instrumental": false, "voice": "warm female alto, half-sung"}
Only "prompt" is required. With no lyrics and instrumental false, the song is instrumental
with the lane's chant sheet (the way ANCHOR's theme songs work); Jarvis normally writes the
lyrics first (frontend/src/lib/music/anchorStudio.ts) by ANCHOR's songbook guide.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import genres, pipeline
from .brief import make_brief
from .config import Profile
from .songbook import Song, bare_tags
from .util import log, seed_from

VOICES = {
    "hardtech": "powerful raw male vocal, shouted festival hooks, clear English",
    "psy": "warm female alto, half-sung and close to the mic, smiles on the long vowels",
    "rap": "confident male rapper, fast clear English bars, every word on the beat",
    "hiphop": "smooth male rapper with a sung hook, laid-back but sharp",
}
ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def lane_for(profile: Profile, req: dict) -> str:
    """The decided lane for a request: a lane named by id or by its genre name, else the one
    the prompt describes (the same classifier that files Anchit's own Suno songs)."""
    active = [l for l in profile.lanes if not l.retired and l.group]
    want = (req.get("genre") or "").strip().lower()
    for lane in active:
        if want and want in (lane.id.lower(), lane.name.lower()):
            return lane.id
    text = " ".join(x for x in (req.get("genre"), req.get("prompt")) if x)
    bpm = int(req["bpm"]) if str(req.get("bpm") or "").isdigit() else None
    lane_id = genres.classify(text, bpm)
    if lane_id not in {l.id for l in active}:
        lane_id = "hardtech"
    return lane_id


def title_for(req: dict) -> str:
    t = re.sub(r"\s+", " ", (req.get("title") or "").strip())[:60]
    if t:
        return t
    words = re.findall(r"[A-Za-z']+", req.get("prompt") or "")
    return " ".join(w.capitalize() for w in words[:3]) or "Untitled"


def song_for(profile: Profile, req: dict, lane_id: str) -> Song | None:
    lyrics = (req.get("lyrics") or "").strip()
    if not lyrics:
        return None
    lane = profile.lane(lane_id)
    group = lane.group or "hardtech"
    return Song(id=f"studio-{req['id']}", title=title_for(req), form="story", groups=(group,),
                voice=(req.get("voice") or VOICES.get(group, VOICES["hardtech"]))[:160],
                about=(req.get("prompt") or "")[:200], lyrics=bare_tags(lyrics),
                model="A" if lane.voice == "rap" else "B")


def brief_maker(profile: Profile, req: dict):
    """The make() hook: one brief per take, built by make_brief with the request's lane, song
    and limits; every three takes draw new sound and seeds (the drop's own retry rule)."""
    lane_id = lane_for(profile, req)
    song = song_for(profile, req, lane_id)
    instrumental = bool(req.get("instrumental")) or song is None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bpm = int(req["bpm"]) if str(req.get("bpm") or "").isdigit() else None
    dur = int(req["duration_s"]) if str(req.get("duration_s") or "").isdigit() else None

    def make(attempt: int, avoid: tuple, variant: str) -> dict:
        b = make_brief(profile, today, [], attempt, avoid, variant=f"studio:{req['id']}:{variant or attempt // 3}",
                       lane_id=lane_id, song=song, instrumental=instrumental,
                       bpm_wanted=bpm, duration_wanted=dur)
        b["title"] = song.title if song else title_for(req)
        b["studio_id"] = req["id"]
        b["seed"] = seed_from("anchor-studio", req["id"], attempt) % 2_000_000_000
        b["prompt"] = req.get("prompt", "")
        return b
    return make


def validate(req: dict) -> dict:
    if not isinstance(req, dict) or not (req.get("prompt") or "").strip():
        raise ValueError("a studio request needs a prompt")
    if not ID.match(str(req.get("id") or "")):
        raise ValueError("a studio request needs an id of 4 to 64 letters, digits, - or _")
    if len(req.get("lyrics") or "") > 6000:
        raise ValueError("lyrics are limited to 6000 characters")
    return req


def run(profile: Profile, req: dict, out_dir: Path, *, engine_name: str | None = None,
        retries: int = 1, deadline: float | None = None) -> dict:
    validate(req)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    log(f"studio {req['id']}: lane {lane_for(profile, req)} for {req['prompt'][:80]!r}")
    meta = pipeline.make(profile, datetime.now(timezone.utc).strftime("%Y-%m-%d"), out_dir,
                         engine_name=engine_name, retries=retries, use_queue=False, deadline=deadline,
                         brief_fn=brief_maker(profile, req), audio_only=True)
    meta.update(id=req["id"], prompt=req["prompt"], seconds=round(time.time() - started))
    return meta
