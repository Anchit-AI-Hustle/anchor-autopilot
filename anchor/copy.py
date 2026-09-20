"""The words under every drop, written the way a person who loves this music talks.

The brief knows the mood arc and the one special moment; the master knows where the record
actually breathes (``audio.arc``). ``write`` hands both to Gemini with the house voice and
gets back a spoken title line and five short paragraphs: a hook, what the record does to you
(with real timestamps), why it was kept, a "play it when", and a question for the comments. Every m:ss the
model writes is checked against the measured arc, so the copy never promises a drop that
isn't there. No key, no network, or a bad answer: ``fallback`` writes the same five parts
from the brief and the arc, seeded by the date so a rerun says the same thing.
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

VOICE = """You write the YouTube title line and description for one techno track, as the person who
made it, talking to a friend. Plain speech: contractions, short sentences, first person, the way
you'd type a message at 2 a.m. about a track you can't stop playing. Not a tagline, not a poem,
not a press release. No fragments stacked for effect ("No mercy. No breakdown. No way back."),
no "immerse yourself", no "journey", no "experience", no emojis, no exclamation marks, no lists,
no hashtags in the text. British spelling. Music is freedom and relief for you; that comes
through in how you talk about it, never as a slogan.

Write as JSON with these keys:
- "line": under 40 characters, lowercase start, no full stop: the thing you'd say about this track to make someone press play. It goes after the title, like "Then Do It — for the second you stop thinking". Not the genre, not the tempo, not the mood word.
- "hook": one sentence, under 120 characters, plain and personal, the first line under the video.
- "body": two to four sentences on what the track actually does, in order, using the timestamps given (as m:ss) and the sound details. Only claim what the facts support.
- "why": one or two sentences, first person, on why you kept this one. Feelings are fine; never invent a specific event that is not in the facts.
- "moment": one sentence starting with "Play it when" naming a real moment for it. No colon needed.
- "ask": one sentence asking the listener something specific about the track, and saying you read every comment.
- "hashtags": three hashtags, the lane's genre first, lowercase, space separated.
Total under 1100 characters. Output only the JSON."""


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
    need = ("hook", "body", "why", "moment", "ask", "hashtags")
    if not all(isinstance(parts.get(k), str) and parts[k].strip() for k in need):
        return None
    text = "\n\n".join(parts[k].strip() for k in need[:-1])
    if len(text) > 1400 or "!" in text or not parts["moment"].startswith("Play it when"):
        return None
    if re.search(r"immers|journey|experience the|unleash", text, re.I):
        return None
    if not _timestamps_ok(text, arc):
        return None
    tags = [t if t.startswith("#") else "#" + t for t in re.split(r"[\s,]+", parts["hashtags"].strip().lower()) if t]
    line = _line_ok(parts.get("line"))
    if not line:
        return None
    return {"line": line, "body": text, "hashtags": " ".join(dict.fromkeys(tags[:3])), "source": "gemini"}


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


def _line_ok(line) -> str | None:
    """The title tail: short, spoken, no genre or tempo in it (they are in the description)."""
    if not isinstance(line, str):
        return None
    line = line.strip().strip(".").strip()
    if not 6 <= len(line) <= 44 or "!" in line or re.search(r"\bbpm\b|techno|rawstyle|acid|industrial", line, re.I):
        return None
    return line[0].lower() + line[1:]


# ------------------------------------------------------------------ fallback writer
HOOKS = ["I've had this one on repeat all week and I'm not tired of it yet.",
         "This is the one I'd play you first if you asked me what I've been making.",
         "I nearly cut this one shorter. Glad I didn't.",
         "Put this on loud and tell me it doesn't move you."]
OPENS = {"industrial": "with the machine already running", "rawstyle": "like a countdown", "hypnotic": "with one figure and no promises",
         "acid": "with the 303 asking a question", "bunker": "in the cold, with the door shut", "cyber": "with the lights flickering"}
WHYS = ["I kept this one for the part of the night when nobody's watching and it still matters.",
        "This came out of a week that needed somewhere to go, so it went here.",
        "I wanted a track that doesn't explain itself, and this one doesn't.",
        "Music is where I get to put everything down. This is what that sounds like."]
MOMENTS = {"industrial": "Play it when the room's empty and you want it to feel bigger.",
           "rawstyle": "Play it when it's the last rep, the last hour, the walk into the room.",
           "hypnotic": "Play it when it's late, you're alone, headphones on, lights off.",
           "acid": "Play it when the night's turned into morning and you're not done.",
           "bunker": "Play it when you need the walls to be concrete for a while.",
           "cyber": "Play it when the city's loud and you want to be louder."}
ASKS = ["Tell me the timestamp that got you. I read every comment.",
        "Where were you when {first} hit? Tell me, I read everything.",
        "Which minute do you keep going back to? Comments are open and I answer."]
LINES = {"industrial": "it never lets up", "rawstyle": "for the last rep", "hypnotic": "lights off for this one",
         "acid": "the 303 does the talking", "bunker": "the walls are concrete", "cyber": "run to this one"}


def fallback(profile: Profile, brief: dict, arc: dict, r: random.Random | None = None) -> dict:
    r = r or rng("anchor-copy", brief["date"])
    lane = profile.lane(brief["lane"])
    drops = [d["at"] for d in arc.get("drops", [])]
    breaks = arc.get("breakdowns", [])
    first = _mmss(drops[0]) if drops else "the first minute"
    length = _mmss(brief.get("duration_s") or arc.get("duration_s") or 0)
    if breaks:
        line = f"the breakdown at {_mmss(breaks[0]['start'])} is the whole track"
        mid = (f"At {_mmss(breaks[0]['start'])} it all falls away for {int(breaks[0]['end'] - breaks[0]['start'])} seconds, "
               f"and when it comes back at {_mmss(breaks[0]['end'])} that's the bit I keep replaying.")
    else:
        line = LINES.get(lane.id, "it never lets up")
        mid = "There's no breakdown in it. It doesn't stop to think, and I didn't want it to."
    if len(drops) > 2:
        line = f"{len(drops)} drops in {length}"
    close = (f"The last lift at {_mmss(drops[-1])} is the one that moves you out the door." if len(drops) > 1 else
             f"{length} long, and I wouldn't cut a bar of it.")
    body = (f"It opens {OPENS.get(lane.id, 'quietly')}, and by {first} the kick has stopped being a sound and started being the floor. "
            f"{mid} {close}") if drops else f"It lands from the first bar and holds. {mid} {close}"
    text = "\n\n".join([r.choice(HOOKS), body, r.choice(WHYS),
                        MOMENTS.get(lane.id, "Play it when it's late and you're still going."),
                        r.choice(ASKS).format(first=first)])
    genre = lane.genre_line.split(",")[0].strip().lower().replace(" ", "")
    return {"line": line, "body": text, "hashtags": " ".join(dict.fromkeys([f"#{genre}", "#hardtechno", "#techno"])), "source": "template"}


def write(profile: Profile, brief: dict, arc: dict) -> dict:
    """Title line + body + hashtags for the drop. Gemini in the house voice, checked; the template otherwise."""
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
