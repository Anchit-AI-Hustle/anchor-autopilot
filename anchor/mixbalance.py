"""Lead and chords over the drums (Anchit, 2026-10-31: "still songs need to be improved much more").

Every local take of 2026-10-30/31 failed the song gate on one check: melody_share, the part of
the sound that is held notes (lead, chords, pads, vocals) rather than hits (kick, hats, claps).
His nine Suno songs sit at 0.805 to 0.918; ACE-Step takes came out at 0.45 to 0.75 with the
drums on top. Neither a bigger model (XL sft, 14 min a take) nor the timbre reference moved
it past 0.79, so the mix does: the take is split into its held part and its hit part (median
filtering, the same split the gate uses) and the hit part is turned down just enough to put
the held part at ``target``, never more than ``max_cut_db``. Nothing is boosted and the kick
stays in; on the 2026-10-31 A/B takes a 4.5 dB cut took melody share from 0.667 to 0.827
(hard techno) and 0.639 to 0.813 (hip hop), and the quiet/loud range went up with it.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from .util import log

GATE_SR, GATE_FFT, GATE_HOP = 22050, 2048, 512


def _gate_split(mono: np.ndarray, sr: int):
    """The held and hit masks at the song gate's own resolution (22.05 kHz, 2048/512) and the
    held share they give: one split per take, reused for the remix."""
    import librosa
    y = librosa.resample(mono, orig_sr=sr, target_sr=GATE_SR) if sr != GATE_SR else mono
    S = np.abs(librosa.stft(y, n_fft=GATE_FFT, hop_length=GATE_HOP))
    mh, mp = librosa.decompose.hpss(S, mask=True)
    h, p = float(((S * mh) ** 2).sum()), float(((S * mp) ** 2).sum())
    return mh, mp, h / (h + p + 1e-12)


def share(mono: np.ndarray, sr: int) -> float:
    """melody_share as the song gate measures it."""
    return _gate_split(mono, sr)[2]


def cut_for(current: float, target: float) -> float:
    """dB the hit part must come down for the held part to be ``target`` of the energy."""
    if current >= target or current <= 0:
        return 0.0
    g2 = current * (1 - target) / (target * (1 - current))
    return float(-10 * np.log10(g2))


def _read(path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf
    y, sr = sf.read(str(path), always_2d=True, dtype="float64")
    return y, sr


def _remix(y: np.ndarray, sr: int, cut_db: float) -> np.ndarray:
    """The take with what each channel's own split hears as hits ``cut_db`` down."""
    import librosa
    n_fft = 1 << int(round(np.log2(GATE_FFT * sr / GATE_SR)))
    hop = n_fft // 4
    g = 10 ** (-cut_db / 20)
    out = []
    for ch in y.T:
        D = librosa.stft(ch, n_fft=n_fft, hop_length=hop)
        mh, mp = librosa.decompose.hpss(np.abs(D), mask=True)
        out.append(librosa.istft(D * (mh + g * mp), hop_length=hop, length=len(ch)))
    z = np.stack(out, 1)
    z *= np.sqrt((y ** 2).mean() / ((z ** 2).mean() + 1e-12))   # same loudness in, the master sets the final level
    peak = float(np.abs(z).max())
    if peak > 0.99:
        z *= 0.99 / peak
    return z


def balance(src: Path, dst: Path, target: float = 0.84, max_cut_db: float = 6.0) -> dict:
    """Write ``src`` to ``dst`` with the drums sat under the lead and chords; returns what it did.
    A take already at ``target`` is copied as it is. Two passes at most: the second splits the
    first pass's mix again and cuts what is still heard as hits (about 3 min a take on the Mac;
    on the 2026-10-31 hard techno take, 0.649 -> 0.835 with 5.3 dB, and the gate passed it)."""
    y, sr = _read(src)
    before = share(y.mean(axis=1), sr)
    total, now, z = 0.0, before, y
    for _ in range(2):
        step = min(cut_for(now, target), max_cut_db - total)
        if step < 0.25:
            break
        z = _remix(z, sr, step)
        total += step
        now = share(z.mean(axis=1), sr)
    pcm = (np.clip(z, -1, 1) * 32767).astype("<i2")
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    info = {"before": round(before, 3), "after": round(now, 3), "drum_cut_db": round(total, 2)}
    log(f"mix: melody share {info['before']} -> {info['after']} (drums down {info['drum_cut_db']} dB under the lead and chords)")
    return info
