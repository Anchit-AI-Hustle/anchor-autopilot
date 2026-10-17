"""Timed lyrics for the full videos: what is sung, and exactly when.

``timed_lines(mp3, work, known=None)`` isolates the vocal (Demucs), transcribes it with word
timestamps (faster-whisper) and, when the real lyric sheet is known (the brief's ``lyrics_sung``),
snaps those words onto the heard timing so the text is the written one and the timing is the sung
one. It returns display lines ``[{"start", "end", "words": [(text, start, end), ...]}]``, or ``[]``
for an instrumental. Every step is optional: a missing model or a failed separation returns what
it has, never an exception, so a song without lyrics still gets its motion video.

``scenes.write_ass`` turns the lines into an ASS karaoke caption: each word fills in the accent
colour as it is sung.
"""
from __future__ import annotations

import difflib
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

from .util import log

MAX_WORDS = 7            # a line on screen
MAX_CHARS = 24          # characters on one line at the video's lyric size
MAX_SPAN = 4.2           # seconds one line may stay on screen
BREAK_GAP = 0.9          # a pause this long always starts a new line
MIN_WORD_PROB = 0.25     # below this the recogniser is guessing
MIN_VOCAL_WORDS = 8      # fewer heard words than this: treat the track as instrumental


def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", w.lower())


def vocal_stem(mp3: Path, work: Path) -> Path | None:
    """The isolated vocal (Demucs, two stems), or None when separation is unavailable."""
    work.mkdir(parents=True, exist_ok=True)
    stem = work / "htdemucs" / mp3.stem / "vocals.wav"
    if stem.exists():
        return stem
    try:
        subprocess.run([sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs",
                        "-o", str(work), str(mp3)], check=True, capture_output=True, timeout=1500)
    except Exception as exc:                                  # demucs missing, out of memory, timeout
        log(f"lyrics: vocal separation unavailable ({str(exc)[:120]})")
        return None
    return stem if stem.exists() else None


def heard_words(audio: Path, title: str | None = None) -> list[tuple[str, float, float]]:
    """(word, start, end) as sung, from faster-whisper. Empty when the model is unavailable.

    No voice-activity filter: on a sung vocal it cut whole phrases out. The song's title is the
    likeliest sung phrase, so it is given as a hint (it was heard as "Super Slonchic Kurt")."""
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("small", device="cpu", compute_type="int8")
        hint = {"hotwords": title, "initial_prompt": f"{title}."} if title else {}
        segs, _info = model.transcribe(str(audio), language="en", word_timestamps=True, vad_filter=False,
                                       condition_on_previous_text=False, beam_size=5, **hint)
        out = []
        for s in segs:
            for w in s.words or []:
                t = w.word.strip()
                if _norm(t) and w.probability >= MIN_WORD_PROB and w.end > w.start:
                    out.append((t, float(w.start), float(w.end)))
        return out
    except Exception as exc:
        log(f"lyrics: transcription unavailable ({str(exc)[:120]})")
        return []


ALIGN_PAD = 0.8          # seconds of vocal either side of a phrase given to the aligner
ALIGN_MAX_SHIFT = 2.5    # an aligned word further than this from where Whisper heard it is not trusted
VOICED_DB = -50.0        # a word whose span on the vocal stem is quieter than this was not sung there


def _load_mono(path: Path, sr: int) -> np.ndarray:
    import soundfile as sf
    x, rate = sf.read(str(path), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if rate != sr:
        import torch
        import torchaudio
        x = torchaudio.functional.resample(torch.from_numpy(x), rate, sr).numpy()
    return x


def align(vocal: Path, words: list[tuple[str, float, float]]) -> list[tuple[str, float, float]]:
    """Whisper's words, re-timed by forced alignment on the vocal stem (wav2vec2 CTC).

    Whisper's word times drift: a phrase after silence starts up to a second early, which put the
    karaoke ahead of the singer. The aligner places every letter on the vocal itself, phrase by
    phrase. Any step that fails leaves Whisper's timing."""
    if not words:
        return words
    try:
        import torch
        import torchaudio
        import torchaudio.functional as F
        bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
        model = bundle.get_model().eval()
        sr = bundle.sample_rate
        idx = {c: i for i, c in enumerate(bundle.get_labels())}
        x = _load_mono(vocal, sr)
    except Exception as exc:                                  # noqa: BLE001 - no model: keep Whisper's times
        log(f"lyrics: alignment unavailable ({str(exc)[:120]})")
        return words
    groups, cur = [], []
    for w in words:
        if cur and w[1] - cur[-1][2] > 1.5:
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    out: list[tuple[str, float, float]] = []
    for g in groups:
        a, b = max(0.0, g[0][1] - ALIGN_PAD), min(len(x) / sr, g[-1][2] + ALIGN_PAD)
        toks, keep = [], []
        for j, (t, _s, _e) in enumerate(g):
            c = "".join(ch for ch in t.upper() if ch in idx and ch != "|")
            if c:
                keep.append((j, len(toks), len(c)))
                toks += [idx[ch] for ch in c]
        try:
            seg = torch.from_numpy(x[int(a * sr):int(b * sr)].copy())[None]
            with torch.inference_mode():
                em, _ = model(seg)
                em = torch.log_softmax(em, dim=-1)
            if not toks or em.shape[1] < len(toks):
                raise ValueError("phrase too short to align")
            ali, sc = F.forced_align(em, torch.tensor([toks], dtype=torch.int32), blank=0)
            spans = F.merge_tokens(ali[0], sc[0].exp())
        except Exception:                                     # noqa: BLE001 - this phrase keeps Whisper's times
            out += g
            continue
        fs = (b - a) / em.shape[1]
        res = list(g)
        for j, k0, n in keep:
            sp = spans[k0:k0 + n]
            s, e = a + sp[0].start * fs, a + sp[-1].end * fs
            if abs(s - g[j][1]) <= ALIGN_MAX_SHIFT:
                res[j] = (g[j][0], round(s, 3), round(max(e, s + 0.08), 3))
        out += res
    fixed, last = [], 0.0                                     # strictly forward in time
    for w, s, e in out:
        s = max(s, last)
        fixed.append((w, s, max(e, s + 0.08)))
        last = s + 0.02
    return fixed


def voiced(vocal: Path, words: list[tuple[str, float, float]], floor_db: float = VOICED_DB) -> list[tuple[str, float, float]]:
    """Only the words that sit on actual singing: with the activity filter off, Whisper can
    invent a word ("You") over an instrumental stretch."""
    try:
        x = _load_mono(vocal, 16000)
    except Exception:                                         # noqa: BLE001
        return words
    keep = []
    for w, s, e in words:
        seg = x[max(0, int((s - 0.05) * 16000)):max(int((e + 0.05) * 16000), int(s * 16000) + 1600)]
        db = 20 * np.log10(float(np.sqrt(np.mean(seg ** 2))) + 1e-9) if len(seg) else -99.0
        if db >= floor_db:
            keep.append((w, s, e))
    return keep


def snap_to_sheet(heard: list[tuple[str, float, float]], sheet: str) -> list[tuple[str, float, float]]:
    """The written words with the sung timing: matched words take the heard time, the gaps
    between matches are spread evenly. Section tags like [Chorus] are not sung and dropped."""
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", sheet)
    words = [w for w in text.split() if _norm(w)]
    if not words or not heard:
        return heard
    a = [_norm(w) for w in words]
    b = [_norm(w[0]) for w in heard]
    match = difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
    anchors: dict[int, tuple[float, float]] = {}
    for blk in match:
        for k in range(blk.size):
            anchors[blk.a + k] = (heard[blk.b + k][1], heard[blk.b + k][2])
    if len(anchors) < max(4, len(words) // 3):               # the sheet does not match the take: trust the ear
        return heard
    out: list[tuple[str, float, float]] = []
    idx = sorted(anchors)
    for i, w in enumerate(words):
        if i in anchors:
            out.append((w, *anchors[i]))
            continue
        prev = max((j for j in idx if j < i), default=None)
        nxt = min((j for j in idx if j > i), default=None)
        if prev is None or nxt is None:                       # before the first or after the last match
            edge = anchors[idx[0]][0] if prev is None else anchors[idx[-1]][1]
            near = idx[0] if prev is None else idx[-1]
            step = 0.35 * (i - near)
            s = max(0.0, edge + step - 0.3) if prev is None else edge + step - 0.3 + 0.05
            out.append((w, s, s + 0.3))
            continue
        t0, t1 = anchors[prev][1], anchors[nxt][0]
        span = (t1 - t0) / (nxt - prev)
        s = t0 + span * (i - prev - 1) + (0 if t1 <= t0 else 0)
        out.append((w, s, s + max(0.15, span * 0.9)))
    # keep strictly forward in time
    fixed, last = [], 0.0
    for w, s, e in out:
        s = max(s, last)
        e = max(e, s + 0.12)
        fixed.append((w, s, e))
        last = s + 0.05
    return fixed


def to_lines(words: list[tuple[str, float, float]], max_chars: int = MAX_CHARS) -> list[dict]:
    """Group words into display lines at pauses, punctuation and a width / time budget. A line
    never overlaps the next one on screen."""
    lines, cur = [], []
    for w, s, e in words:
        if cur:
            gap = s - cur[-1][2]
            span = e - cur[0][1]
            ended = cur[-1][0].rstrip().endswith((".", "!", "?", ","))
            chars = sum(len(c[0]) + 1 for c in cur) + len(w)
            if gap > BREAK_GAP or len(cur) >= MAX_WORDS or chars > max_chars or span > MAX_SPAN or (ended and len(cur) >= 3):
                lines.append(cur)
                cur = []
        cur.append((w, s, e))
    if cur:
        lines.append(cur)
    out = []
    for i, ln in enumerate(lines):
        end = ln[-1][2]
        if i + 1 < len(lines):
            end = min(end, lines[i + 1][0][1] - 0.05)         # never past the next line's first word
        out.append({"start": ln[0][1], "end": max(end, ln[0][1] + 0.2), "words": ln})
    return out


def timed_lines(mp3: Path, work: Path, known: str | None = None, title: str | None = None) -> list[dict]:
    if os.environ.get("ANCHOR_LYRICS", "1") == "0":            # tests and hosts without the models
        return []
    stem = vocal_stem(mp3, work)
    heard = heard_words(stem or mp3, title)
    if stem and heard:
        heard = voiced(stem, align(stem, heard))
    if len(heard) < MIN_VOCAL_WORDS and not known:
        log(f"lyrics: {mp3.name}: {len(heard)} words heard, instrumental")
        return []
    words = snap_to_sheet(heard, known) if known else heard
    lines = to_lines(words)
    log(f"lyrics: {mp3.name}: {len(words)} words in {len(lines)} lines" + (" (sheet-aligned)" if known else ""))
    return lines


def lines_for(mp3: Path, work: Path, known: str | None = None, title: str | None = None) -> list[dict]:
    """``timed_lines`` that never raises and is cached beside the song, so a re-render of the
    same master reuses the transcription."""
    import json
    cache = work / "lines.json"
    try:
        if cache.exists():
            return [{**ln, "words": [tuple(w) for w in ln["words"]]} for ln in json.loads(cache.read_text())]
        lines = timed_lines(mp3, work, known, title)
        work.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(lines))
        return lines
    except Exception as exc:
        log(f"lyrics: skipped for {mp3.name}: {str(exc)[:160]}")
        return []


# ---------------------------------------------------------------- ASS helpers (used by scenes.py)

def _t(sec: float) -> str:
    sec = max(0.0, sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _bgr(hexcol: str, alpha: int = 0) -> str:
    h = hexcol.lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper().replace("&H", "&H")


def _esc(w: str) -> str:
    return w.replace("{", "(").replace("}", ")").replace("\\", "")
