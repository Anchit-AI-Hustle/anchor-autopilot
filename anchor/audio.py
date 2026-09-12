"""Audio mastering, analysis, quality gates and Short excerpt selection."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np

from .util import run

SR = 48_000


def decode(path: Path, sr: int = SR) -> np.ndarray:
    """Decode any audio file to float32 stereo [n, 2] via ffmpeg."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(sr), "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return np.frombuffer(proc.stdout, dtype="<f4").reshape(-1, 2).copy()


def loudness(path: Path) -> dict:
    """Integrated loudness (LUFS), true peak (dBTP) and LRA via ffmpeg loudnorm."""
    proc = run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af",
                "loudnorm=print_format=json", "-f", "null", "-"], quiet=True)
    blob = re.findall(r"\{[^{}]*\}", proc.stdout, re.S)[-1]
    data = json.loads(blob)
    return {k: float(data[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh")}


def master(src: Path, dst: Path, lufs: float = -11.0, tp: float = -1.0) -> dict:
    """Gain + true-peak-safe limiter, iterated until loudness is within 0.4 LU of the target.

    The limiter runs at 192 kHz (4x oversampling) so inter-sample peaks - big on distorted
    kicks - are caught too. Writes 48 kHz 16-bit WAV.
    """
    before = loudness(src)
    ceiling = 10 ** ((tp - 0.3) / 20)
    gain = lufs - before["input_i"]
    after = before
    for _ in range(3):
        chain = (f"highpass=f=22,volume={gain:.2f}dB,aresample=192000:resampler=soxr,"
                 f"alimiter=limit={ceiling:.4f}:attack=4:release=60:level=0,aresample={SR}:resampler=soxr")
        run(["ffmpeg", "-y", "-hide_banner", "-v", "error", "-i", src, "-af", chain,
             "-ar", str(SR), "-c:a", "pcm_s16le", dst], quiet=True)
        after = loudness(dst)
        miss = lufs - after["input_i"]
        if abs(miss) <= 0.4:
            break
        gain += miss
    return {"before": before, "after": after, "gain_db": round(gain, 2)}


def encode_mp3(src: Path, dst: Path, kbps: int = 256) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-c:a", "libmp3lame", "-b:a", f"{kbps}k", dst], quiet=True)


def encode_flac(src: Path, dst: Path) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-c:a", "flac", dst], quiet=True)


def _db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


def estimate_bpm(mono: np.ndarray, sr: int = SR, lo: float = 110, hi: float = 190) -> float | None:
    """Tempo via a comb over the onset-envelope autocorrelation (8 beat multiples, 0.1 BPM grid).

    Summing several multiples of the beat period removes the plateau ambiguity of a single
    autocorrelation peak, so the estimate lands within ~0.2 BPM on steady four-on-the-floor material.
    """
    step, hop, win = 4, 64, 1024
    x = mono[: len(mono) // step * step].reshape(-1, step).mean(axis=1)  # 12 kHz
    if len(x) < win * 16:
        return None
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop] * np.hanning(win)
    flux = np.maximum(np.diff(np.log1p(np.abs(np.fft.rfft(frames, axis=1))), axis=0), 0).sum(axis=1)
    flux = flux - flux.mean()
    ac = np.correlate(flux, flux, mode="full")[len(flux) - 1:]
    if ac[0] <= 0:
        return None
    ac = ac / ac[0]
    env_fs = sr / step / hop
    grid = np.arange(lo, hi, 0.1)
    periods = 60.0 * env_fs / grid                          # frames per beat
    pos = periods[:, None] * np.arange(1, 9)[None, :]       # 8 multiples per candidate
    valid = pos < len(ac) - 1
    vals = np.interp(np.where(valid, pos, 0.0), np.arange(len(ac)), ac) * valid
    scores = vals.sum(axis=1) / np.maximum(valid.sum(axis=1), 1)
    return round(float(grid[int(np.argmax(scores))]), 1)


def analyze(audio: np.ndarray, sr: int = SR) -> dict:
    mono = audio.mean(axis=1)
    n = len(mono)
    duration = n / sr
    finite = bool(np.isfinite(audio).all())
    rms = float(np.sqrt(np.mean(mono ** 2))) if n else 0.0
    peak = float(np.max(np.abs(audio))) if n else 0.0
    clip_ratio = float(np.mean(np.abs(audio) >= 0.999)) if n else 0.0
    # 0.5 s windows for dropout detection (middle 80 % of the track)
    w = sr // 2
    win_rms = np.sqrt(np.mean(mono[: n // w * w].reshape(-1, w) ** 2, axis=1)) if n >= w else np.array([])
    win_db = 20 * np.log10(np.maximum(win_rms, 1e-9))
    lo, hi = int(len(win_db) * 0.1), int(len(win_db) * 0.9)
    longest = run_len = 0
    for v in win_db[lo:hi]:
        run_len = run_len + 1 if v < -45 else 0
        longest = max(longest, run_len)
    # low-end share: energy below 150 Hz
    spec = np.abs(np.fft.rfft(mono[: min(n, sr * 60)]))
    freqs = np.fft.rfftfreq(min(n, sr * 60), 1 / sr)
    total = float(np.sum(spec ** 2)) or 1.0
    low_ratio = float(np.sum(spec[freqs < 150] ** 2) / total)
    return {
        "duration_s": round(duration, 2),
        "finite": finite,
        "rms_db": round(_db(rms), 2),
        "peak_db": round(_db(peak), 2),
        "clip_ratio": round(clip_ratio, 6),
        "longest_dropout_s": longest * 0.5,
        "low_ratio": round(low_ratio, 3),
        "bpm_est": estimate_bpm(mono, sr),
    }


def quality_gate(stats: dict, brief: dict) -> tuple[bool, list[str], list[str]]:
    """Hard failures block publishing; warnings are recorded but let the drop through."""
    fail, warn = [], []
    if not stats["finite"]:
        fail.append("audio contains NaN/Inf")
    if abs(stats["duration_s"] - brief["duration_s"]) > 3:
        fail.append(f"duration {stats['duration_s']}s vs target {brief['duration_s']}s")
    if stats["rms_db"] < -30:
        fail.append(f"too quiet / near silent (RMS {stats['rms_db']} dBFS)")
    if stats["longest_dropout_s"] >= 2.5:
        fail.append(f"dropout of {stats['longest_dropout_s']}s inside the track")
    if stats["low_ratio"] < 0.05:
        fail.append(f"no low end (kick/bass share {stats['low_ratio']})")
    elif stats["low_ratio"] < 0.12:
        warn.append(f"light low end (share {stats['low_ratio']})")
    if stats["clip_ratio"] > 0.01:
        warn.append(f"clipping in raw render ({stats['clip_ratio'] * 100:.2f}% samples)")
    est, target = stats.get("bpm_est"), brief["bpm"]
    if est:
        ratios = [abs(est - target), abs(est * 2 - target), abs(est / 2 - target)]
        if min(ratios) > 5:
            warn.append(f"tempo landed at {est} BPM (asked {target})")
    return (not fail), fail, warn


def best_window(audio: np.ndarray, bpm: int, seconds: float, sr: int = SR) -> tuple[float, float]:
    """Loudest/busiest stretch of ``seconds`` aligned to whole bars. Returns (start_s, length_s)."""
    mono = audio.mean(axis=1)
    duration = len(mono) / sr
    bar = 4 * 60.0 / bpm
    n_bars = max(1, round(seconds / bar))
    length = n_bars * bar
    if length >= duration - 0.5:
        return 0.0, min(length, duration)
    # grid origin: first strong onset (tracks rarely start exactly on sample 0)
    env = np.abs(mono)
    thresh = 0.3 * float(np.max(env) or 1.0)
    first = int(np.argmax(env > thresh)) / sr
    origin = first % bar
    bar_energy = []
    starts = np.arange(origin, duration - length, bar)
    for s in starts:
        seg = mono[int(s * sr): int((s + length) * sr)]
        # energy + transient density, favouring material after the intro
        e = float(np.sqrt(np.mean(seg ** 2)))
        d = float(np.mean(np.abs(np.diff(seg)))) if len(seg) > 1 else 0.0
        bar_energy.append(e + 0.5 * d)
    if not bar_energy:
        return 0.0, min(length, duration)
    scores = np.array(bar_energy)
    intro_bars = 8  # gently prefer windows that start after the intro
    if len(scores) > intro_bars + 1:
        scores[:intro_bars] *= 0.85
    best = int(np.argmax(scores))
    return round(float(starts[best]), 3), round(length, 3)


def cut(src: Path, dst: Path, start: float, length: float, fade_in: float = 0.35, fade_out: float = 1.6) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", src,
         "-af", f"afade=t=in:st=0:d={fade_in},afade=t=out:st={max(0.0, length - fade_out):.3f}:d={fade_out}",
         "-ar", str(SR), "-c:a", "pcm_s16le", dst], quiet=True)
