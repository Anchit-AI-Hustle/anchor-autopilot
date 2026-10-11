"""The spectrum bars of the scene videos, drawn from the audio itself.

ffmpeg's own spectrum filters are dominated by the kick on techno (one fat bass blob), so the
bars are computed here: log-spaced bands, each judged against its own typical level over the
whole track so highs and mids move as much as the bass, with a fast attack and a slower fall.
``frames`` yields raw RGBA canvases (``W`` x ``h``) for ffmpeg to read from a pipe; during the
given ``big`` ranges (breakdowns) the bars grow to fill the canvas, mirrored about its centre.
"""
from __future__ import annotations

import numpy as np

from .audio import SR

BANDS = 72
N_FFT = 4096


def band_levels(mono: np.ndarray, fps: int, n_frames: int, sr: int = SR, bands: int = BANDS,
                fmin: float = 45.0, fmax: float = 14000.0) -> np.ndarray:
    """(n_frames, bands) in 0..1: the level of each band against its own typical level."""
    hop = sr / fps
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / sr)
    edges = np.geomspace(fmin, fmax, bands + 1)
    idx = [np.where((freqs >= lo) & (freqs < hi))[0] for lo, hi in zip(edges[:-1], edges[1:])]
    idx = [i if len(i) else np.array([int(np.searchsorted(freqs, lo))]) for i, lo in zip(idx, edges[:-1])]
    win = np.hanning(N_FFT).astype(np.float32)
    pad = np.pad(mono.astype(np.float32), (N_FFT // 2, 2 * N_FFT + int(4 * hop)))
    db = np.empty((n_frames, bands), dtype=np.float32)
    for start in range(0, n_frames, 256):
        stop = min(n_frames, start + 256)
        offs = (np.arange(start, stop) * hop).astype(int)
        blk = np.stack([pad[o:o + N_FFT] for o in offs]) * win
        mag = np.abs(np.fft.rfft(blk, axis=1)) ** 2
        for b, ix in enumerate(idx):
            db[start:stop, b] = 10 * np.log10(mag[:, ix].mean(axis=1) + 1e-9)
    ref = np.percentile(db, 95, axis=0)
    norm = np.clip((db - (ref - 28.0)) / 28.0, 0.0, 1.0) ** 1.4
    out = np.empty_like(norm)                                  # fast attack, slower fall
    cur = np.zeros(bands, dtype=np.float32)
    for k in range(n_frames):
        up = norm[k] > cur
        cur = np.where(up, cur + (norm[k] - cur) * 0.85, cur + (norm[k] - cur) * 0.22)
        out[k] = cur
    return out


def draw(levels: np.ndarray, width: int, height: int, rgb: tuple[int, int, int], big: bool,
         base: int = 150) -> bytes:
    """One RGBA canvas. Small: bars rising from the bottom edge, ``base`` px tall at most.
    Big: mirrored about the vertical centre, using the whole height."""
    canvas = np.zeros((height, width, 4), dtype=np.uint8)
    n = len(levels)
    gap = 3
    bw = max(2, int((width * 0.94) / n) - gap)
    x0 = (width - n * (bw + gap)) // 2
    col = np.array([*rgb, 205], dtype=np.uint8)
    cap = np.array([min(255, rgb[0] + 90), min(255, rgb[1] + 90), min(255, rgb[2] + 90), 255], dtype=np.uint8)
    for i, v in enumerate(levels):
        x = x0 + i * (bw + gap)
        if big:
            h = max(3, int(v * (height / 2 - 6) * 0.62))
            mid = height // 2
            canvas[mid - h:mid + h, x:x + bw] = col
            canvas[mid - h:mid - h + 4, x:x + bw] = cap
            canvas[mid + h - 4:mid + h, x:x + bw] = cap
        else:
            h = max(3, int(v * base))
            canvas[height - h:height - 8, x:x + bw] = col
            canvas[height - h:height - h + 4, x:x + bw] = cap
    return canvas.tobytes()


def frames(mono: np.ndarray, fps: int, n_frames: int, width: int, height: int, rgb: tuple[int, int, int],
           big_ranges: list[tuple[float, float]], base: int = 150):
    lv = band_levels(mono, fps, n_frames)
    for k in range(n_frames):
        t = k / fps
        yield draw(lv[k], width, height, rgb, any(a <= t < b for a, b in big_ranges), base)
