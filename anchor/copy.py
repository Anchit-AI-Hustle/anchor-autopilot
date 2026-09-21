"""The words under every drop, written the way a person who loves this music talks.

The brief knows the mood arc and the one special moment; the master knows where the record
actually breathes (``audio.arc``). ``write`` hands both to Gemini with the house voice and
gets back three short lines: what the track does,
the timestamps that matter, and a question for the comments. Every m:ss the
model writes is checked against the measured arc, so the copy never promises a drop that
isn't there. No key, no network, or a bad answer: ``fallback`` writes the same five parts
from the arc, seeded by the date so a rerun says the same thing. Short on purpose: a phone
shows about 50 characters of a title and two lines of a description.
"""
from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.request

from .config import Profile, env
from .util import log, rng

MODEL = "gemini-2.5-flash"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

VOICE = """You write the YouTube description for one techno track, as the person who
made it, talking to a friend. Plain speech, first person, short. Not a tagline, not a poem, not a
press release. No "immerse", "journey", "experience", no emojis, no exclamation marks, no lists,
no hashtags in the text. British spelling.

Write as JSON with these keys:
- "l1": one sentence, under 60 characters, what the track does or why you kept it.
- "l2": one sentence, under 60 characters, the timestamps that matter (as m:ss), from the facts only.
- "ask": one short question about the track, under 50 characters.
- "hashtags": three hashtags, the lane's genre first, lowercase, space separated.
Output only the JSON."""


def _mmss(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def facts(profile: Profile, brief: dict, arc: dict) -> dict:
    lane = profile.lane(brief["lane"])
    events = [{"at": _mmss(d["at"]), "what": "drop"} for d in arc.get("drops", [])]
    events += [{"at": _mmss(b["start"]), "what": f"breakdown for {int(b['end'] - b['start'])} s"} for b in arc.get("breakdowns", [])]
    events.sort(key=lambda e: e["at"])
    return {
        "title": brief["title"], "genre": lane.genre_line.split(",")[0].strip(), "bpm": int(brief["bpm"]),
        "length": _mmss(brief.get("duration_s") or arc.get("duration_s") or 0),
        "sung_hook": brief.get("hook"), "mood": brief.get("mood"), "special_moment": brief.get("special"),
        "textures": brief.get("textures"), "vocals": "sung hook" if brief.get("hook") else "instrumental",
        "arc": events or "steady the whole way, no breakdown",
    }


def _timestamps_ok(text: str, arc: dict, tolerance_s: int = 3) -> bool:
    """Every m:ss the writer used must sit on a measured event."""
    marks = {round(d["at"]) for d in arc.get("drops", [])} | {round(b["start"]) for b in arc.get("breakdowns", [])} | \
            {round(b["end"]) for b in arc.get("breakdowns", [])}
    for m, s in re.findall(r"\b(\d{1,2}):(\d{2})\b", text):
        t = int(m) * 60 + int(s)
        if not any(abs(t - x) <= tolerance_s for x in marks):
            return False
    return True


def _clean(parts: dict, arc: dict) -> dict | None:
    need = ("l1", "l2", "ask", "hashtags")
    if not all(isinstance(parts.get(k), str) and parts[k].strip() for k in need):
        return None
    l1, l2, ask = (parts[k].strip() for k in need[:-1])
    if max(len(l1), len(l2)) > 90 or len(ask) > 80 or "!" in l1 + l2 + ask:
        return None
    if re.search(r"immers|journey|experience the|unleash", l1 + l2, re.I) or not _timestamps_ok(l1 + " " + l2, arc):
        return None
    tags = [t if t.startswith("#") else "#" + t for t in re.split(r"[\s,]+", parts["hashtags"].strip().lower()) if t]
    return {"body": f"{l1}\n{l2}\n{ask.rstrip('?')}? I read every comment.",
            "hashtags": " ".join(dict.fromkeys(tags[:3])), "source": "gemini"}


def ask_gemini(prompt: str, api_key: str, timeout_s: int = 60, attempts: int = 2) -> str:
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.9, "responseMimeType": "application/json"}}).encode()
    req = urllib.request.Request(ENDPOINT.format(model=MODEL), data=body, method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
    last = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                data = json.loads(resp.read().decode())
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (urllib.error.URLError, KeyError, IndexError, ValueError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(10)
    raise RuntimeError(f"gemini copy: {last}")


# ------------------------------------------------------------------ fallback writer
L1 = {"industrial": "A dry kick in a big room. It never lets up.", "rawstyle": "A kick with a tail you feel in your teeth.",
      "hypnotic": "One figure, turning until it becomes a room.", "acid": "A 303 that keeps changing its question.",
      "bunker": "Cold, dry, the door shut behind you.", "cyber": "Neon bass and a kick that snarls."}
ASKS = ["Where did it get you?", "Which drop is yours?", "Which minute do you replay?"]


def fallback(profile: Profile, brief: dict, arc: dict, r: random.Random | None = None) -> dict:
    r = r or rng("anchor-copy", brief["date"])
    lane = profile.lane(brief["lane"])
    drops = [_mmss(d["at"]) for d in arc.get("drops", [])]
    breaks = arc.get("breakdowns", [])
    if breaks:
        l2 = f"Falls away at {_mmss(breaks[0]['start'])}, back at {_mmss(breaks[0]['end'])}. Wait for it."
    elif drops:
        l2 = f"Drops at {', '.join(drops[:4])}. No breakdown."
    else:
        l2 = "Steady the whole way. No breakdown, on purpose."
    body = "\n".join([L1.get(lane.id, "Hard, dry, unhurried."), l2, f"{r.choice(ASKS)} I read every comment."])
    genre = lane.genre_line.split(",")[0].strip().lower().replace(" ", "")
    return {"body": body, "hashtags": " ".join(dict.fromkeys([f"#{genre}", "#hardtechno", "#techno"])), "source": "template"}


def write(profile: Profile, brief: dict, arc: dict) -> dict:
    """Body + hashtags for the drop. Gemini in the house voice, checked; the template otherwise."""
    key = env("GEMINI_API_KEY")
    if key and env("ANCHOR_COPY", "gemini") != "template":
        prompt = VOICE + "\n\nFacts (JSON):\n" + json.dumps(facts(profile, brief, arc), ensure_ascii=False)
        for attempt in range(3):
            try:
                parts = json.loads(ask_gemini(prompt, key))
                out = _clean(parts if isinstance(parts, dict) else {}, arc)
                if out:
                    return out
                log(f"copy: attempt {attempt + 1} rejected (voice or timestamps), retrying")
            except (RuntimeError, ValueError) as exc:
                log(f"copy: {exc}")
    out = fallback(profile, brief, arc)
    log("copy: written from the template")
    return out
