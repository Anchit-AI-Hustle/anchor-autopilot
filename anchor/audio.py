"""Audio mastering, analysis, quality gates and Short excerpt selection."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np

from .util import log, run

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


def music_end(audio: np.ndarray, sr: int = SR, floor_db: float = -40.0) -> float:
    """The second at which the music actually stops, ignoring rendered padding.

    The model writes N seconds whether or not it has N seconds of music, so the file often
    ends in several seconds of digital silence. Fading the end of the FILE fades that
    silence and leaves the cliff untouched, which is exactly what happened on 2026-09-12.
    """
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    step = max(1, int(0.1 * sr))
    frames = np.array([np.sqrt(np.mean(np.square(mono[i:i + step])) + 1e-12)
                       for i in range(0, len(mono) - step, step)])
    if not len(frames):
        return len(mono) / sr
    live = np.where(frames > frames.max() * 10 ** (floor_db / 20))[0]
    if not len(live):
        return len(mono) / sr
    return round(float((live[-1] + 1) * step / sr), 3)


def ends_abruptly(audio: np.ndarray, sr: int = SR, tail_s: float = 1.0,
                  margin_db: float = 6.0) -> tuple[bool, float]:
    """Is this track still at full level when it runs out?

    A model asked for N seconds renders N seconds and stops mid-bar, so the last sample is
    as loud as the middle of the track. A track that actually resolves has already dropped
    away by then. Returns (abrupt, how many dB down the tail is).
    """
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    # Trailing silence is padding, not an ending: a model asked for 150 s renders music to
    # 147 s and pads the rest, so measuring the literal last second measures the padding.
    step = max(1, int(0.1 * sr))
    frames = np.array([np.sqrt(np.mean(np.square(mono[i:i + step])) + 1e-12)
                       for i in range(0, len(mono) - step, step)])
    if not len(frames):
        return False, 0.0
    live = np.where(frames > frames.max() * 10 ** (-40 / 20))[0]
    if not len(live):
        return False, 0.0
    mono = mono[: (live[-1] + 1) * step]
    n = int(tail_s * sr)
    if len(mono) < n * 2:
        return False, 0.0
    body = float(np.sqrt(np.mean(np.square(mono[: -n])) + 1e-12))
    tail = float(np.sqrt(np.mean(np.square(mono[-n:])) + 1e-12))
    drop = 20.0 * np.log10(body / tail) if tail > 0 else 99.0
    return bool(drop < margin_db), round(float(drop), 2)


def master(src: Path, dst: Path, lufs: float = -11.0, tp: float = -1.0,
           outro_fade_s: float = 0.0) -> dict:
    """Gain + true-peak-safe limiter, iterated until loudness is within 0.4 LU of the target.

    The limiter runs at 192 kHz (4x oversampling) so inter-sample peaks - big on distorted
    kicks - are caught too. Writes 48 kHz 16-bit WAV.

    If the track is still at full level on its last second it was cut off rather than ended,
    so an outro fade is applied. A track that already resolves is left alone - fading a real
    ending twice only makes it limp.
    """
    before = loudness(src)
    ceiling = 10 ** ((tp - 0.3) / 20)
    gain = lufs - before["input_i"]
    after = before

    fade, cut = "", []
    abrupt, tail_db, end = False, 0.0, 0.0
    if outro_fade_s > 0:
        raw = decode(src)
        abrupt, tail_db = ends_abruptly(raw)
        if abrupt:
            # Fade into where the MUSIC stops and cut there. Using the file length puts the
            # fade inside the trailing silence, which fades nothing and keeps the cliff.
            end = music_end(raw)
            start = max(0.0, end - outro_fade_s)
            fade = f",afade=t=out:st={start:.3f}:d={outro_fade_s:.3f}"
            cut = ["-t", f"{end:.3f}"]
            log(f"master: music stops at {end:.1f}s of {probe_duration(src):.1f}s and is only "
                f"{tail_db} dB down - fading the last {outro_fade_s:.1f}s and trimming the padding")

    for _ in range(3):
        chain = (f"highpass=f=22,volume={gain:.2f}dB,aresample=192000:resampler=soxr,"
                 f"alimiter=limit={ceiling:.4f}:attack=4:release=60:level=0,"
                 f"aresample={SR}:resampler=soxr{fade}")
        run(["ffmpeg", "-y", "-hide_banner", "-v", "error", "-i", src, "-af", chain,
             *cut, "-ar", str(SR), "-c:a", "pcm_s16le", dst], quiet=True)
        after = loudness(dst)
        miss = lufs - after["input_i"]
        if abs(miss) <= 0.4:
            break
        gain += miss
    return {"before": before, "after": after, "gain_db": round(gain, 2),
            "tail_db": tail_db, "outro_fade_s": outro_fade_s if fade else 0.0,
            "music_end_s": end or None}


def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def encode_mp3(src: Path, dst: Path, kbps: int = 256, *, tags: dict | None = None,
               cover: Path | None = None) -> None:
    """Encode to MP3 carrying its own title, artist and cover art.

    ID3v2.3 on purpose: ffmpeg defaults to 2.4, which Windows Explorer and plenty of car
    stereos do not read, so a downloaded track shows up as its filename over a blank square.
    """
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
    if cover and Path(cover).exists():
        cmd += ["-i", str(cover), "-map", "0:a", "-map", "1:v", "-c:v", "mjpeg",
                "-disposition:v", "attached_pic",
                "-metadata:s:v", "title=Album cover",
                "-metadata:s:v", "comment=Cover (front)"]
    cmd += ["-c:a", "libmp3lame", "-b:a", f"{kbps}k", "-id3v2_version", "3", "-write_id3v1", "1"]
    for key, value in (tags or {}).items():
        if value not in (None, ""):
            cmd += ["-metadata", f"{key}={value}"]
    run(cmd + [str(dst)], quiet=True)


def encode_flac(src: Path, dst: Path) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-c:a", "flac", dst], quiet=True)


def _db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


def estimate_bpm(mono: np.ndarray, sr: int = SR, lo: float = 110, hi: float = 190) -> float | None:
    """Tempo via a comb over the onset-envelope autocorrelation (8 beat multiples, 0.1 BPM grid).

    Summing several multiples of the beat period removes the plateau ambiguity of a single
    autocorrelation peak, so the estimate lands within ~0.2 BPM on steady four-on-the-floor material.
    """
    env = onset_envelope(mono, sr)
    if env is None:
        return None
    flux, env_fs = env
    ac = np.correlate(flux, flux, mode="full")[len(flux) - 1:]
    if ac[0] <= 0:
        return None
    ac = ac / ac[0]
    grid = np.arange(lo, hi, 0.1)
    periods = 60.0 * env_fs / grid                          # frames per beat
    pos = periods[:, None] * np.arange(1, 9)[None, :]       # 8 multiples per candidate
    valid = pos < len(ac) - 1
    vals = np.interp(np.where(valid, pos, 0.0), np.arange(len(ac)), ac) * valid
    scores = vals.sum(axis=1) / np.maximum(valid.sum(axis=1), 1)
    return round(float(grid[int(np.argmax(scores))]), 1)


ENV_LAG = 14          # onset-envelope latency in frames (window 1024 / hop 64 at 12 kHz)


def onset_envelope(mono: np.ndarray, sr: int = SR) -> tuple[np.ndarray, float] | None:
    """Spectral-flux onset envelope and its frame rate - the basis for tempo and beat phase."""
    step, hop, win = 4, 64, 1024
    x = mono[: len(mono) // step * step].reshape(-1, step).mean(axis=1)  # 12 kHz
    if len(x) < win * 16:
        return None
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop] * np.hanning(win)
    flux = np.maximum(np.diff(np.log1p(np.abs(np.fft.rfft(frames, axis=1))), axis=0), 0).sum(axis=1)
    return flux - flux.mean(), sr / step / hop


def beat_phase(mono: np.ndarray, bpm: float, sr: int = SR) -> float:
    """Seconds from the start of the audio to the first beat of the grid at ``bpm``.

    The Short pulses the cover on the beat, so it needs the grid's phase, not just its tempo:
    a cut that starts a fraction of a beat early makes every pulse read as off-beat.
    """
    beat = 60.0 / float(bpm)
    env = onset_envelope(mono, sr)
    if env is None:
        return 0.0
    flux, env_fs = env
    period = beat * env_fs
    if period < 2 or len(flux) < period * 4:
        return 0.0
    offsets = np.arange(0.0, period, 0.25)
    grids = offsets[:, None] + np.arange(0, (len(flux) - 1) / period) * period
    scores = np.interp(grids, np.arange(len(flux)), flux).mean(axis=1)
    # a flux frame fires once its window has swallowed the onset, so it reads ENV_LAG frames early
    phase = (float(offsets[int(np.argmax(scores))]) + ENV_LAG) / env_fs
    return round(phase % beat, 4)


KEY_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# Krumhansl-Kessler key profiles, normalised
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def estimate_key(mono: np.ndarray, sr: int = SR) -> tuple[str, float] | None:
    """Best-matching key and a 0-1 confidence, from a chroma profile of the mid band.

    Techno is mostly percussion, so the bass drum and hats are filtered out before the
    chroma is taken; the confidence is the margin between the best key and the runner-up.
    """
    if len(mono) < sr * 5:
        return None
    step = 4                                   # 12 kHz is plenty for pitch classes
    x = mono[: len(mono) // step * step].reshape(-1, step).mean(axis=1)
    sr_d = sr / step
    win = 8192
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[:: win // 2]
    if len(frames) < 4:
        return None
    spec = np.abs(np.fft.rfft(frames * np.hanning(win), axis=1)).mean(axis=0)
    freqs = np.fft.rfftfreq(win, 1 / sr_d)
    band = (freqs > 110) & (freqs < 2200)      # above the kick, below the hats
    f, mag = freqs[band], np.log1p(spec[band])
    chroma = np.zeros(12)
    np.add.at(chroma, (np.round(12 * np.log2(f / 440.0)).astype(int) + 9) % 12, mag)
    if chroma.sum() <= 0:
        return None
    chroma = chroma / chroma.sum()
    scores = []
    for i in range(12):
        rolled = np.roll(chroma, -i)
        scores.append((float(np.corrcoef(rolled, _MAJOR)[0, 1]), f"{KEY_NAMES[i]} major"))
        scores.append((float(np.corrcoef(rolled, _MINOR)[0, 1]), f"{KEY_NAMES[i]} minor"))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1]
    confidence = max(0.0, min(1.0, (best[0] - second[0]) * 5))
    return best[1], round(confidence, 2)


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
