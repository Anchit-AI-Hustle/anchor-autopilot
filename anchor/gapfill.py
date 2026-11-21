"""Short dropouts mended with the bar before them, so a good take is not lost to a glitch.

ACE-Step sometimes leaves a few hundred milliseconds of digital silence or a sudden dip in the
middle of a take (2026-11-21, Sky Belongs To Nobody at 181 BPM: holes of 0.3 to 0.8 s at 74 s,
94 s, 146 s, 202 s and 234 s; every take held by the song gate, nothing posted). Anchit's rule
is no gaps or breaks mid-song (2026-11-01), and the song gate holds every take that has one.

A hole or dip no longer than one bar is filled with the same span one bar earlier, with short
crossfades at both seams: hard techno repeats bar by bar, so the listener hears the groove carry
on instead of a gap. Anything longer than a bar is left alone and the gate still holds it, and
the first and last 5 seconds (intro and fade) are never touched. The song gate and the lyric
check then judge the mended take like any other.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .util import log

SILENT = 1e-4          # the gate's digital silence: every channel under -80 dBFS
EDGE_S = 5.0
FADE_S = 0.01


def _runs(mask: np.ndarray):
    flips = np.flatnonzero(np.diff(np.concatenate([[0], mask.astype(np.int8), [0]])))
    return list(zip(flips[::2], flips[1::2]))


def gaps(y: np.ndarray, sr: int, bpm: float) -> list[tuple[int, int]]:
    """Sample spans to mend: digital-silence runs over 20 ms and dips 18 dB under the 4 s median
    lasting 0.2 s or more (the gate's two measures), each no longer than one bar."""
    from scipy.ndimage import median_filter
    mono = np.abs(y).max(axis=1) if y.ndim > 1 else np.abs(y)
    edge, bar = int(EDGE_S * sr), int(4 * 60.0 / bpm * sr)
    spans = [(a, b) for a, b in _runs(mono < SILENT) if b - a >= 0.25 * sr]
    hop = int(0.05 * sr)
    n = len(mono) // hop
    m = (y.mean(axis=1) if y.ndim > 1 else y)[: n * hop].reshape(n, hop)
    db = 20 * np.log10(np.sqrt((m ** 2).mean(axis=1) + 1e-12) + 1e-9)
    low = db < median_filter(db, size=81, mode="nearest") - 18
    spans += [(a * hop, b * hop) for a, b in _runs(low) if b - a >= 4]
    out = []
    for a, b in sorted(spans):
        a, b = max(0, a - int(0.01 * sr)), min(len(mono), b + int(0.01 * sr))
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return [(a, b) for a, b in out if b - a <= bar and a - bar >= 0 and edge < a and b < len(mono) - edge]


def mend(y: np.ndarray, sr: int, bpm: float) -> tuple[np.ndarray, list[tuple[float, float]]]:
    """``y`` with every short gap filled from one bar earlier; and the mended spans in seconds."""
    y = np.array(y, dtype=np.float64, copy=True)
    bar, fade = int(4 * 60.0 / bpm * sr), max(1, int(FADE_S * sr))
    done = []
    for a, b in gaps(y, sr, bpm):
        src = y[a - bar:b - bar].copy()
        # only where the bar before plays something there: a sparse pattern repeats its own
        # space, and copying space onto space changes nothing
        if np.sqrt((src ** 2).mean()) < 4 * np.sqrt((y[a:b] ** 2).mean()) + 1e-6:
            continue
        ramp = np.linspace(0.0, 1.0, min(fade, (b - a) // 2) or 1)
        w = np.ones(b - a)
        w[:len(ramp)] = ramp
        w[len(w) - len(ramp):] = np.minimum(w[len(w) - len(ramp):], ramp[::-1])
        w = w[:, None] if y.ndim > 1 else w
        y[a:b] = y[a:b] * (1 - w) + src * w
        done.append((round(a / sr, 2), round((b - a) / sr, 2)))
    return y, done


def mend_file(path: Path, bpm: float, out: Path | None = None) -> tuple[Path, list[tuple[float, float]]]:
    try:
        import scipy  # noqa: F401  (the gate's measures)
        import soundfile as sf
        y, sr = sf.read(str(path), always_2d=True)
        fixed, done = mend(y, sr, float(bpm))
    except Exception as exc:       # noqa: BLE001  a take is never lost to the mend step
        log(f"gapfill: left as rendered ({exc})")
        return path, []
    if not done:
        return path, []
    out = out or path.with_name(path.stem + "-mended.wav")
    sf.write(str(out), np.clip(fixed, -1.0, 1.0), sr, subtype="PCM_16")
    log(f"gapfill: mended {len(done)} short gap(s) with the bar before: {done[:6]}")
    return out, done
