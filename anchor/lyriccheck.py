"""Does the song sing its own production notes? (Anchit, 2026-10-26: "many of the songs have
lyrics which are actually meant to be the type of the music at that point".)

The lyrics sheet once carried each section's direction inside its tag ("[drop - full punchy kick,
bouncing bassline in ..., shouted crowd chant]"), and the small planner model sang those notes:
Transmit Pressure (2026-10-25-2) sings "for eight to sixteen bars ... the room drops away, a
playful tease of the hook, rap verse, laid back flow over the groove"; Elastic Orbit sings the
breakdown direction twice. The sheet now carries bare section tags, and every rendered take is
listened to: the words heard (faster-whisper) are compared with the words written, and any run of
three words that comes from the production vocabulary but not from the written lyrics fails the
take, which is then rendered again.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from .util import log

# Phrases a direction, tag or delivery note is made of; anything the arranger is told and the
# singer must never say. Built from the live directions (music.SECTION_DIRECTIONS and the brief's
# VOICE tables) plus the stock words of a lyric sheet.
STOCK_NOTES = [
    "rap verse", "verse one", "verse two", "pre chorus", "build up", "the drop", "breakdown",
    "instrumental", "eight bars", "sixteen bars", "eight to sixteen bars", "bar by bar",
    "confident flow on the beat", "laid back flow over the groove", "faster flow building to the hook",
    "whispered voice", "whispered voice getting louder", "shouted crowd chant", "crowd chant building",
    "a playful tease of the hook", "the room drops away", "over a held chord", "kick and sub fully out",
    "filter opening", "filter closing", "snare roll and riser", "every element pulled back in",
    "pressure rising bar by bar", "resolve to silence", "bigger and bouncier than the first drop",
    "full punchy kick", "bouncing bassline in", "catchy main hook at peak energy", "the whole room jumping",
    "filtered kick alone", "no sub bass yet", "tension only", "hi hats", "kick and bass strip back",
]


NUMBERS = {"1": "one", "2": "two", "4": "four", "8": "eight", "16": "sixteen", "32": "thirty two"}


def enabled() -> bool:
    """On in real runs; tests switch it off with ANCHOR_LYRIC_CHECK=0 (see tests/conftest.py)."""
    import os
    return (os.environ.get("ANCHOR_LYRIC_CHECK") or "1").lower() not in ("0", "off", "false", "no")


def _words(text: str) -> list[str]:
    text = text.lower().replace("-", " ")
    out = []
    for t in text.split():
        w = re.sub(r"[^a-z0-9']+", "", t)
        if w:
            out += NUMBERS.get(w, w).split()             # the recogniser writes "8 to 16 bars"
    return out


def _grams(words: list[str], n: int = 3) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def note_vocabulary() -> list[str]:
    """Every production note the sheet or the arranger could carry."""
    from . import brief, music
    notes = list(STOCK_NOTES) + list(music.SECTION_DIRECTIONS.values())
    for table in (brief.VOICE, brief.VOICE_RAP):
        notes += [delivery for delivery, _kind in table.values()]
    # the {t0}/{t1}/{t2} texture slots are filled per song; the words around them still count
    return [re.sub(r"\{t\d\}", " ", n) for n in notes]


def lyric_bank() -> list[str]:
    """Every whisper, shout and rap bar the profile can write into a song."""
    try:
        from .config import load_profile
        voice = load_profile().music["voice"]
    except Exception:                                 # noqa: BLE001 - no profile: nothing extra allowed
        return []
    from . import themes
    theme_lines = [line for t in themes.load() for line in (*t.whispers, *t.chants, *t.rap)]
    return [*voice.get("whispers", []), *voice.get("shouts", []), *voice.get("rap", []), *theme_lines]


def sung_lines(sheet: str | None) -> list[str]:
    """The words meant to be sung: every line of the sheet that is not a [tag]."""
    return [ln.strip() for ln in (sheet or "").splitlines() if ln.strip() and not ln.strip().startswith("[")]


def sung_notes(heard: str, sheet: str | None, notes: list[str] | None = None) -> list[str]:
    """The production notes heard in the vocal: three-word runs that belong to a note and are not
    in the written lyrics. Empty when the song sings only what it was written to sing."""
    notes = note_vocabulary() if notes is None else notes
    # what was written is always allowed, and so is anything from the channel's own lyric banks
    # ("the whole room rises" is a rap bar, not a direction)
    allowed = _grams(_words(" ".join(sung_lines(sheet)))) | _grams(_words(" ".join(lyric_bank())))
    note_grams = set()
    for n in notes:
        note_grams |= _grams(_words(n))
    heard_words = _words(heard)
    hits, i = [], 0
    while i <= len(heard_words) - 3:
        g = tuple(heard_words[i:i + 3])
        if g in note_grams and g not in allowed:
            j = i + 3                                    # widen to the whole sung note for the report
            while j < len(heard_words) and tuple(heard_words[j - 2:j + 1]) in note_grams:
                j += 1
            hits.append(" ".join(heard_words[i:j]))
            i = j
        else:
            i += 1
    return hits


def hear(audio: Path, title: str | None = None, model_size: str = "small") -> str | None:
    """What the vocal says, as text (faster-whisper on CPU). None when the recogniser is not
    installed or fails, so a missing model never blocks a song; it is reported instead."""
    try:
        import soundfile as sf
        from faster_whisper import WhisperModel
    except Exception as exc:                          # noqa: BLE001
        log(f"lyriccheck: recogniser unavailable ({str(exc)[:120]})")
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "mono16k.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(audio), "-ac", "1", "-ar", "16000", str(wav)],
                           check=True, capture_output=True)
            samples, _sr = sf.read(str(wav), dtype="float32")
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        # no hint with the title: a prompt makes the recogniser spell the title right even when
        # the singer says it wrong, and the pronunciation check below needs to hear what was sung
        segs, _info = model.transcribe(samples, language="en", vad_filter=False,
                                       condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segs)
    except Exception as exc:                          # noqa: BLE001
        log(f"lyriccheck: transcription failed ({str(exc)[:160]})")
        return None


def _close(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def misheard_title(heard: str, title: str | None, min_ratio: float = 0.8, min_exact: float = 0.75) -> list[str]:
    """The words of the title that were not sung as standard English (Anchit, 2026-10-30:
    "kinetic", "carbon" were pronounced wrong). The title is the chant of every drop, sung many
    times. A word is sung wrong when the recogniser never hears it as itself, or when most of
    what it hears near it is a variant: Kinetic Carbon (2026-10-26-3) was heard as "kinetic" 9
    times and "kinected" 4 times. Short words (under 4 letters) are not judged."""
    words = [w for w in _words(title or "") if len(w) >= 4]
    if not words:
        return []
    seq = _words(heard)
    # the recogniser may glue or split a sung word: also look at each pair of heard words joined
    cands = seq + [a + b for a, b in zip(seq, seq[1:])]
    bad = []
    for w in words:
        if not any(_close(w, h) >= min_ratio for h in cands):
            bad.append(w)
            continue
        joined, i = [], 0                      # a sung word heard split in two counts as itself
        while i < len(seq):
            if i + 1 < len(seq) and seq[i] + seq[i + 1] == w:
                joined.append(w)
                i += 2
            else:
                joined.append(seq[i])
                i += 1
        near = [h for h in joined if len(h) >= 3 and _close(w, h) >= 0.6]
        exact = sum(1 for h in near if h == w or h.rstrip("s") == w)
        if near and exact / len(near) < min_exact:
            bad.append(w)
    return bad


def check(audio: Path, sheet: str | None, title: str | None = None) -> dict:
    """{"heard": text or None, "notes": [sung production notes], "misheard": [title words sung
    wrong], "checked": bool}."""
    heard = hear(audio, title)
    if heard is None:
        return {"heard": None, "notes": [], "misheard": [], "checked": False}
    notes = sung_notes(heard, sheet)
    sung = sung_lines(sheet)
    # the title is judged only when the sheet sings it (a queued song's sheet may be unknown)
    misheard = misheard_title(heard, title) if title and any(title.lower() in ln.lower() for ln in sung) else []
    log(f"lyriccheck: {len(_words(heard))} words heard; "
        + (f"SINGS PRODUCTION NOTES: {notes}" if notes else "only the written lyrics")
        + (f"; TITLE SUNG WRONG: {misheard}" if misheard else ""))
    return {"heard": heard, "notes": notes, "misheard": misheard, "checked": True}


VERIFIED = Path(__file__).resolve().parent.parent / "site" / "data" / "lyrics_verified.json"


def unchecked(drop_dir: Path, verified: Path | None = None) -> bool:
    """True for a rendered drop whose takes were never listened to (made before this check
    existed) and that nobody has verified by hand since: it must not be posted."""
    import json
    verified = VERIFIED if verified is None else verified
    meta_path = Path(drop_dir) / "meta.json"
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text())
        attempts = (meta.get("qc") or {}).get("attempts") or []
        if any("heard" in a for a in attempts):
            return False
        ids = set(json.loads(verified.read_text()).get("ids", [])) if verified.exists() else set()
        return (meta.get("brief") or {}).get("id") not in ids
    except (OSError, ValueError):
        return True
