"""The words under every drop: the vibe and the theme, hyped, and nothing mechanical.

No timestamps, no track anatomy, no tempo in the body (the footer carries genre and BPM).
``write`` hands the brief's mood, theme and textures to Gemini with the house voice and gets
back two to four short sentences that build like an intro. Anything with a clock time, an
exclamation mark, an em dash or marketing words is rejected. No key, no network, or a bad
answer: ``fallback`` writes the same from the brief, seeded by the date so a rerun says the
same thing. Short on purpose: a phone shows two lines of a description.
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

VOICE = """You write the YouTube description for one techno track, as the person who made it,
hyping it up to a friend. Give the vibe and the theme of the record, nothing else: what it
feels like, what it's about, where it takes you. Build it like an intro: short sentences that
get bigger. Plain speech, first person is fine, British spelling.

Never: timestamps or clock times, tempo or BPM, section names (intro, drop, breakdown, build),
"immerse", "journey", "experience", emojis, exclamation marks, em dashes, lists, hashtags in
the text.

Write as JSON with these keys:
- "body": two to four sentences, under 260 characters in total.
- "hashtags": three hashtags, the lane's genre first, lowercase, space separated.
Output only the JSON."""

BANNED = re.compile(r"\b\d{1,2}:\d{2}\b|\bbpm\b|\bdrop\b|\bbreakdown\b|\bintro\b|immers|journey|experience|unleash|[!" + "\u2014\u2013" + "]", re.I)


def facts(profile: Profile, brief: dict) -> dict:
    lane = profile.lane(brief["lane"])
    return {
        "title": brief["title"], "genre": lane.genre_line.split(",")[0].strip(),
        "mood": brief.get("mood"), "theme": brief.get("special"), "textures": brief.get("textures"),
        "sung_hook": brief.get("hook"), "vocals": "sung hook" if brief.get("hook") else "instrumental",
    }


def _clean(parts: dict) -> dict | None:
    body = parts.get("body")
    if not isinstance(body, str) or not body.strip():
        return None
    body = " ".join(body.split())
    if len(body) > 320 or BANNED.search(body):
        return None
    tags = [t if t.startswith("#") else "#" + t for t in re.split(r"[\s,]+", str(parts.get("hashtags", "")).strip().lower()) if t]
    if len(tags) < 3:
        return None
    return {"body": body, "hashtags": " ".join(dict.fromkeys(tags[:3])), "source": "gemini"}


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
OPENERS = {"industrial": "Warehouse pressure with no off switch.", "rawstyle": "A kick you feel in your teeth and a floor that won't stay under you.",
           "hypnotic": "One figure, turning until it becomes a room you're standing in.", "acid": "A 303 that keeps asking and never waits for the answer.",
           "bunker": "Concrete, steel, and the cold coming up through your shoes.", "cyber": "Neon bass and a kick pushed until it snarls."}
CLOSERS = ["Turn it up and let it take the week off your hands.", "Once it starts there's no way back up. You won't want one.",
           "Lights off. Let it run.", "Play it too loud. That's the point."]


def _sentence(text: str) -> str:
    text = " ".join((text or "").split()).strip().rstrip(".")
    return text[0].upper() + text[1:] + "." if text else ""


def fallback(profile: Profile, brief: dict, r: random.Random | None = None) -> dict:
    r = r or rng("anchor-copy", brief["date"])
    lane = profile.lane(brief["lane"])
    # the brief's mood and theme are written for the music engine and can name sections; only the clean ones are quoted
    quotes = [_sentence(brief.get(k)) for k in ("mood", "special")]
    parts = [OPENERS.get(lane.id, "Hard, dry, and in no hurry."), *[q for q in quotes if q and not BANNED.search(q)], r.choice(CLOSERS)]
    body = " ".join(parts)
    genre = lane.genre_line.split(",")[0].strip().lower().replace(" ", "")
    return {"body": " ".join(body.split()), "hashtags": " ".join(dict.fromkeys([f"#{genre}", "#hardtechno", "#techno"])), "source": "template"}


def write(profile: Profile, brief: dict, arc: dict | None = None) -> dict:
    """Body + hashtags for the drop. Gemini in the house voice, checked; the template otherwise.
    ``arc`` is accepted and ignored: the words no longer quote the record's clock."""
    key = env("GEMINI_API_KEY")
    if key and env("ANCHOR_COPY", "gemini") != "template":
        prompt = VOICE + "\n\nFacts (JSON):\n" + json.dumps(facts(profile, brief), ensure_ascii=False)
        for attempt in range(3):
            try:
                parts = json.loads(ask_gemini(prompt, key))
                out = _clean(parts if isinstance(parts, dict) else {})
                if out:
                    return out
                log(f"copy: attempt {attempt + 1} rejected (voice, clock time or banned word), retrying")
            except (RuntimeError, ValueError) as exc:
                log(f"copy: {exc}")
    out = fallback(profile, brief)
    log("copy: written from the template")
    return out
