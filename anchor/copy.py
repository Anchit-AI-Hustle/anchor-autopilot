"""The words under every drop, written the way a person who loves this music talks.

The brief knows the mood arc and the one special moment; the master knows where the record
actually breathes (``audio.arc``). ``write`` hands both to Gemini with the house voice and
gets back five short paragraphs: a hook, what the record does to you (with real timestamps),
a line about why it exists, a "play it when", and a question for the comments. Every m:ss the
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

VOICE = """You write the YouTube description for one techno track, as the person who made it.
You love this music. Music is freedom, relief, a place to put a week down; you live inside
each beat and you talk to the listener like a friend at 2 a.m., warm, physical, specific.
Never marketing voice, never "immerse yourself", never "experience", never "journey", never
emojis, never exclamation marks, never a list. British spelling. Short sentences are fine.

Write five parts, as JSON with these keys:
- "hook": one sentence, under 120 characters, that could be the first line of a story (YouTube shows it above the fold).
- "body": two to four sentences about what the record does to you, in order, using the real timestamps given (write them as m:ss) and the given sound details. Only claim what the facts support.
- "why": one or two sentences in first person about why this record exists or when you made it. Honest, small, human. Never claim a specific personal event that is not in the facts; feelings are fine.
- "moment": one line starting with "Play it when:" naming a real-life moment for this record.
- "ask": one sentence that asks the listener a specific question about the track for the comments, and says you read them.
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
    if len(text) > 1400 or "!" in text or not parts["moment"].startswith("Play it when:"):
        return None
    if re.search(r"immers|journey|experience the|unleash", text, re.I):
        return None
    if not _timestamps_ok(text, arc):
        return None
    tags = [t if t.startswith("#") else "#" + t for t in re.split(r"[\s,]+", parts["hashtags"].strip().lower()) if t]
    return {"body": text, "hashtags": " ".join(dict.fromkeys(tags[:3])), "source": "gemini"}


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
HOOKS = ["{Mood}. That is the whole record, and it is enough.",
         "Some records ask for your attention. This one takes your shoulders.",
         "You do not listen to this one so much as stand inside it.",
         "{Special}. Everything before that is the walk there."]
BODIES = ["It opens {open}, and by {first} the kick has stopped being a sound and started being the floor. {mid} {close}",
          "The first minute is {open}. {first_s} {mid} {close}"]
OPENS = {"industrial": "with the machine already running", "rawstyle": "like a countdown", "hypnotic": "with one figure and no promises",
         "acid": "with the 303 asking a question", "bunker": "in the cold, with the door shut", "cyber": "with the lights flickering"}
WHYS = ["I make these for the part of the night when nobody is watching and it still matters.",
        "This one came out of a week that needed somewhere to go. It went here.",
        "I wanted a record that does not explain itself, so it does not.",
        "Music is the one place I get to put everything down. This is the sound of putting it down."]
MOMENTS = {"industrial": "Play it when: the room is empty and you want it to feel bigger.",
           "rawstyle": "Play it when: the last rep, the last hour, the walk into the room.",
           "hypnotic": "Play it when: late, alone, headphones, lights off.",
           "acid": "Play it when: the night turns into morning and you are not done.",
           "bunker": "Play it when: you need the walls to be concrete for a while.",
           "cyber": "Play it when: the city is loud and you want to be louder."}
ASKS = ["Tell me the timestamp that got you. I read every comment.",
        "Where were you when {first} hit? Tell me. I read everything.",
        "Which minute is the one you keep going back to? Comments are open and I answer."]


def fallback(profile: Profile, brief: dict, arc: dict, r: random.Random | None = None) -> dict:
    r = r or rng("anchor-copy", brief["date"])
    lane = profile.lane(brief["lane"])
    drops = [d["at"] for d in arc.get("drops", [])]
    breaks = arc.get("breakdowns", [])
    first = _mmss(drops[0]) if drops else "the first minute"
    mood = (brief.get("mood") or "hard and unhurried").strip().rstrip(".")
    special = (brief.get("special") or "one moment where it all lets go").strip().rstrip(".")
    Mood, Special = mood[0].upper() + mood[1:], special[0].upper() + special[1:]
    mid = (f"At {_mmss(breaks[0]['start'])} it falls away for {int(breaks[0]['end'] - breaks[0]['start'])} seconds, and the return is the part you will replay."
           if breaks else "There is no breakdown, because nothing here stops to think.")
    close = (f"The last lift at {_mmss(drops[-1])} is the one that moves you out the door." if len(drops) > 1 else
             f"{Special}: listen for it.")
    body = r.choice(BODIES).format(open=OPENS.get(lane.id, "quietly"), first=first, first_s=f"The first drop lands at {first}." if drops else "It lands from the first bar.",
                                   mid=mid, close=close)
    text = "\n\n".join([r.choice(HOOKS).format(Mood=Mood, Special=Special), body, r.choice(WHYS),
                        MOMENTS.get(lane.id, "Play it when: it is late and you are still going."),
                        r.choice(ASKS).format(first=first)])
    genre = lane.genre_line.split(",")[0].strip().lower().replace(" ", "")
    return {"body": text, "hashtags": " ".join(dict.fromkeys([f"#{genre}", "#hardtechno", "#techno"])), "source": "template"}


def write(profile: Profile, brief: dict, arc: dict) -> dict:
    """Body + hashtags for the drop. Gemini in the house voice, checked; the template otherwise."""
    key = env("GEMINI_API_KEY")
    if key and env("ANCHOR_COPY", "gemini") != "template":
        prompt = VOICE + "\n\nFacts (JSON):\n" + json.dumps(facts(profile, brief, arc), ensure_ascii=False)
        for attempt in range(2):
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
