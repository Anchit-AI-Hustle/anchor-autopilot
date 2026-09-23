"""What the channel taught the robot: the craft checks and the finishing pass every record gets.

Measured on 2026-09-23 over the audio YouTube serves for all 21 videos (the six-axis
rating in the Rupture Pulse report). The lowest-rated records shared three faults, and
the best-performing one (Engage Gravity, the most views per day) had none of them:

- almost all the energy below 60 Hz, which a phone speaker does not play (Rupture Pulse
  87%, the channel median 47%): on a phone the record is a quiet tick;
- a narrow, near-mono image (width 0.09 against a median 0.28);
- no breakdown: one loop at one level from start to finish (a single 6 s dip), where the
  records people stay with fall away for 10 to 20 s at 10 to 14 dB and come back.

So a generated take must break down and must move, or it is sent back for another seed;
and every master, generated or your own, goes through ``enhance`` first: the sub a little
lower, its harmonics added where a phone can play them, the kick's click and the air
lifted, the image above 250 Hz widened with the bass kept mono. The pass only does as
much as a record needs, and nothing at all to one that already sits in the channel's range.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

SR = 48_000

# the channel's medians on 2026-09-23 (21 videos) and the gates derived from them
MEDIAN = {"phone_share": 0.36, "width": 0.28, "contrast_db": 8.7, "movement": 0.55}
GATE = {"breakdown_s": 8.0, "breakdown_db": 8.0, "movement": 0.30}
TARGET = {"phone_share": 0.28, "width": 0.22}   # where the finishing pass aims, just under the medians


# ------------------------------------------------------------------------ measure
def _spectrum(mono: np.ndarray, sr: int = SR) -> tuple[np.ndarray, np.ndarray]:
    win = np.hanning(8192)
    f = np.fft.rfftfreq(8192, 1 / sr)
    acc = np.zeros(len(f))
    for s in range(0, max(1, len(mono) - 8192), sr // 2):
        seg = mono[s:s + 8192]
        if len(seg) < 8192:
            break
        acc += np.abs(np.fft.rfft(seg * win)) ** 2
    return f, acc


def phone_share(mono: np.ndarray, sr: int = SR) -> float:
    """Share of the audible energy a phone speaker plays: half of 60-250 Hz, all above 250."""
    f, acc = _spectrum(mono, sr)
    tot = acc[(f >= 20) & (f < 16000)].sum() or 1.0
    low = acc[(f >= 60) & (f < 250)].sum()
    high = acc[(f >= 250) & (f < 16000)].sum()
    return float((0.5 * low + high) / tot)


def width(audio: np.ndarray) -> float:
    if audio.ndim == 1 or audio.shape[1] < 2:
        return 0.0
    mid, side = (audio[:, 0] + audio[:, 1]) / 2, (audio[:, 0] - audio[:, 1]) / 2
    return float(np.sqrt((side ** 2).mean()) / (np.sqrt((mid ** 2).mean()) + 1e-9))


def breakdowns(mono: np.ndarray, sr: int = SR, win_s: float = 2.0) -> list[dict]:
    """Stretches at least GATE['breakdown_db'] under the loudest part, away from the edges."""
    n = int(win_s * sr)
    if len(mono) < 6 * n:
        return []
    fr = mono[: len(mono) // n * n].reshape(-1, n)
    rms = 20 * np.log10(np.sqrt((fr ** 2).mean(axis=1)) + 1e-9)
    sm = np.convolve(rms, np.ones(3) / 3, mode="same")
    peak, total = float(np.percentile(sm, 95)), len(sm) * win_s
    out, start = [], None
    for i, q in enumerate(list(sm < peak - GATE["breakdown_db"]) + [False]):
        if q and start is None:
            start = i
        elif not q and start is not None:
            t0, t1 = start * win_s, i * win_s
            if t0 > 0.08 * total and t1 < 0.92 * total:
                out.append({"start": t0, "length": t1 - t0, "depth_db": round(float(sm[start:i].min() - peak), 1)})
            start = None
    return out


def movement(mono: np.ndarray, sr: int = SR) -> float:
    """How much the sound changes from one 16 s block to the next (band energies, z-scored)."""
    from .unique import band_sequence
    seq = band_sequence(mono, sr)
    blocks = [seq[i:i + 32].mean(axis=0) for i in range(0, len(seq) - 32, 32)]
    if len(blocks) < 2:
        return 0.0
    return float(np.mean([np.abs(blocks[i + 1] - blocks[i]).mean() for i in range(len(blocks) - 1)]))


def measure(audio: np.ndarray, sr: int = SR) -> dict:
    mono = audio.mean(axis=1) if audio.ndim == 2 else audio
    n = 2 * sr
    fr = mono[: len(mono) // n * n].reshape(-1, n) if len(mono) >= n else mono[None, :]
    rms = 20 * np.log10(np.sqrt((fr ** 2).mean(axis=1)) + 1e-9)
    body = rms[2:-2] if len(rms) > 6 else rms
    return {"phone_share": round(phone_share(mono, sr), 3), "width": round(width(audio), 3),
            "contrast_db": round(float(np.percentile(body, 95) - np.percentile(body, 10)), 1),
            "movement": round(movement(mono, sr), 3), "breakdowns": breakdowns(mono, sr)}


def gate(m: dict) -> list[str]:
    """Reasons a generated take is sent back. Empty means it passes."""
    fails = []
    real = [b for b in m["breakdowns"] if b["length"] >= GATE["breakdown_s"]]
    if not real:
        fails.append(f"no breakdown (needs {GATE['breakdown_s']:.0f} s at least {GATE['breakdown_db']:.0f} dB under the peak; "
                     "the channel's top record has two)")
    if m["movement"] < GATE["movement"]:
        fails.append(f"one loop start to finish (movement {m['movement']:.2f}, needs {GATE['movement']}; median {MEDIAN['movement']})")
    return fails


# ------------------------------------------------------------------------- enhance
def _band(n: int, sr: int, lo: float, hi: float, edge: float = 0.25) -> np.ndarray:
    """A smooth zero-phase band mask for an rfft of length-n signal (edges a quarter octave)."""
    f = np.fft.rfftfreq(n, 1 / sr)
    lf = np.log2(np.maximum(f, 1.0))
    m = np.ones_like(f)
    if lo > 0:
        m *= np.clip((lf - np.log2(lo)) / edge + 0.5, 0, 1)
    if hi < sr / 2:
        m *= np.clip((np.log2(hi) - lf) / edge + 0.5, 0, 1)
    return m


def _shelf_curve(n: int, sr: int, sub_db: float, pres_db: float, air_db: float) -> np.ndarray:
    f = np.fft.rfftfreq(n, 1 / sr)
    lf = np.log2(np.maximum(f, 1.0))
    g_db = sub_db * np.clip((np.log2(70) - lf) / 0.7, 0, 1)                    # below ~45 Hz, full cut
    g_db += pres_db * np.exp(-((lf - np.log2(3000)) / 0.8) ** 2)                 # the kick's click
    g_db += air_db * np.clip((lf - np.log2(7000)) / 1.0, 0, 1)                   # air
    return 10 ** (g_db / 20)


def enhance(audio: np.ndarray, sr: int = SR, strength: float | None = None) -> tuple[np.ndarray, dict]:
    """The finishing pass. ``strength`` 0..1; by default it is worked out from how far the
    record sits from the targets, so a record already in range is returned untouched."""
    before = measure(audio, sr)
    # tone and width are worked out separately: a record can be wide enough and still inaudible
    # on a phone (Engage Gravity), and widening it further only thins the centre
    gap_phone = max(0.0, (TARGET["phone_share"] - before["phone_share"]) / TARGET["phone_share"])
    gap_width = max(0.0, (TARGET["width"] - before["width"]) / TARGET["width"])
    tone = float(np.clip(gap_phone * 1.25, 0.0, 1.0)) if strength is None else strength
    spread = float(np.clip(gap_width * 1.25, 0.0, 1.0)) if strength is None else strength
    strength = max(tone, spread)
    if strength < 0.05:
        return audio, {"strength": 0.0, "before": before, "after": before}
    x = audio if audio.ndim == 2 else np.stack([audio, audio], axis=1)
    n = len(x)
    mid, side = (x[:, 0] + x[:, 1]) / 2, (x[:, 0] - x[:, 1]) / 2
    M, S = np.fft.rfft(mid), np.fft.rfft(side)
    # harmonics of the 35-80 Hz sub, placed where a phone plays them
    sub = np.fft.irfft(M * _band(n, sr, 35, 80), n)
    peak = np.abs(sub).max() + 1e-9
    harm = np.fft.irfft(np.fft.rfft(np.tanh(6 * sub / peak)) * _band(n, sr, 100, 350), n) * peak
    mid = mid + harm * (10 ** ((-9 + 6 * tone) / 20) if tone > 0 else 0.0)
    # tone and width
    curve = _shelf_curve(n, sr, -5 * tone, 5 * tone, 4.5 * tone)
    M = np.fft.rfft(mid) * curve
    S = S * curve * (1 + 2.5 * spread * _band(n, sr, 250, sr / 2))
    S = S * _band(n, sr, 120, sr / 2)                                               # the bass stays mono
    mid, side = np.fft.irfft(M, n), np.fft.irfft(S, n)
    out = np.stack([mid + side, mid - side], axis=1)
    out = (out / (np.abs(out).max() + 1e-9) * 0.9).astype(np.float32)
    return out, {"strength": round(strength, 2), "tone": round(tone, 2), "spread": round(spread, 2),
                 "before": before, "after": measure(out, sr)}


def enhance_file(src: Path, dst: Path) -> dict:
    from .audio import decode
    from .music import write_wav
    out, info = enhance(decode(src))
    write_wav(dst, out)
    return info
