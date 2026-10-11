"""Where a track changes: its sections, cut to the bar grid.

``sections(audio, bpm, offset)`` listens to a master (a numpy array from ``audio.decode``) and
returns the scenes of its video: ``[{"start", "end", "kind", "variant", "bars"}]`` in seconds.
Every cut lands on a bar line of the measured beat grid, so a scene change is on the "one", and
a long drop is cut every 8 bars so the picture keeps changing with the phrasing. ``kind`` is one
of intro / build / groove / drop / breakdown / outro.

The downbeat is found from the music (the beat position, of the four in a bar, where the
loudness jumps most) rather than assumed from the first kick.
"""
from __future__ import annotations

import numpy as np

from .audio import SR

MIN_BARS = 4            # a scene is never shorter than this
CHUNK_BARS = 8          # a long stretch is cut at this phrase length
LONG_BARS = 16          # longer than this gets cut
HIGH_DB = -3.0          # energy relative to the loud part, dB
LOW_DB = -9.0


def _band_energy(mono: np.ndarray, sr: int, starts: np.ndarray, beat_n: int) -> np.ndarray:
    """(n_beats, 3) energy in dB for low (<150 Hz), mid (150-2k) and high (>2k) per beat."""
    out = np.full((len(starts), 3), -90.0)
    win = np.hanning(beat_n)
    freqs = np.fft.rfftfreq(beat_n, 1.0 / sr)
    lo, mid = freqs < 150, (freqs >= 150) & (freqs < 2000)
    hi = freqs >= 2000
    for i, s in enumerate(starts):
        seg = mono[s:s + beat_n]
        if len(seg) < beat_n:
            seg = np.pad(seg, (0, beat_n - len(seg)))
        spec = np.abs(np.fft.rfft(seg * win)) ** 2
        for j, m in enumerate((lo, mid, hi)):
            out[i, j] = 10 * np.log10(spec[m].sum() / beat_n + 1e-12)
    return out


def _downbeat(total_db: np.ndarray) -> int:
    """Which of the four beats in a bar starts the bar: the one where loudness jumps up most."""
    best, score = 0, -1e9
    for p in range(4):
        idx = np.arange(p + 4, len(total_db) - 4, 4)
        if len(idx) < 3:
            continue
        pwm = lambda x: 10 * np.log10((10 ** (x / 10)).mean() + 1e-12)   # noqa: E731
        jump = [pwm(total_db[i:i + 4]) - pwm(total_db[i - 4:i]) for i in idx]
        s = float(np.mean(np.square(jump)))                    # squared: a jump on the bar line beats the same jump split over two
        if s > score:
            best, score = p, s
    return best


def sections(audio: np.ndarray, bpm: float, offset: float, sr: int = SR) -> list[dict]:
    mono = audio.mean(axis=1) if audio.ndim == 2 else audio
    duration = len(mono) / sr
    beat = 60.0 / float(bpm)
    n_beats = int((duration - offset) // beat)
    if n_beats < 4 * MIN_BARS * 2:                            # too short to have a structure
        return [{"start": 0.0, "end": duration, "kind": "drop", "variant": 0, "bars": max(1, n_beats // 4)}]
    starts = ((offset + np.arange(n_beats) * beat) * sr).astype(int)
    bands = _band_energy(mono, sr, starts, int(beat * sr))
    total = 10 * np.log10((10 ** (bands / 10)).sum(axis=1) + 1e-12)
    p = _downbeat(total)
    first = p                                                  # beat index of the first bar line
    n_bars = (n_beats - first) // 4
    if n_bars < MIN_BARS * 2:
        return [{"start": 0.0, "end": duration, "kind": "drop", "variant": 0, "bars": max(1, n_bars)}]
    def pw(x):                                                  # mean power over a bar, back in dB (a dead beat must not sink it)
        return 10 * np.log10((10 ** (x / 10)).mean() + 1e-12)
    bar_db = np.array([pw(total[first + 4 * b:first + 4 * b + 4]) for b in range(n_bars)])
    bar_low = np.array([pw(bands[first + 4 * b:first + 4 * b + 4, 0]) for b in range(n_bars)])
    loud = np.percentile(bar_db, 90)
    low_ref = np.percentile(bar_low, 90)
    # energy: how loud the bar is against the loud part, with the kick/bass presence counting extra
    e = (bar_db - loud) + 0.5 * np.minimum(0, bar_low - low_ref)
    e = np.convolve(np.pad(e, 1, mode="edge"), np.ones(3) / 3, mode="valid")
    state = np.where(e > HIGH_DB, 2, np.where(e < LOW_DB, 0, 1))

    runs: list[list[int]] = []                                 # [state, first_bar, n_bars]
    for b, s in enumerate(state):
        if runs and runs[-1][0] == s:
            runs[-1][2] += 1
        else:
            runs.append([int(s), b, 1])
    # a run shorter than MIN_BARS is absorbed by its longer neighbour
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, r in enumerate(runs):
            if r[2] < MIN_BARS:
                nb = i - 1 if (i > 0 and (i + 1 >= len(runs) or runs[i - 1][2] >= runs[i + 1][2])) else i + 1
                runs[nb][2] += r[2]
                if nb > i:
                    runs[nb][1] = r[1]
                del runs[i]
                changed = True
                break
    # dance music changes on the 8-bar phrase: pull a boundary within 2 bars of one onto it
    for i in range(1, len(runs)):
        b = runs[i][1]
        snap = round(b / CHUNK_BARS) * CHUNK_BARS
        if snap != b and abs(snap - b) <= 2:
            d = snap - b
            if runs[i - 1][2] + d >= MIN_BARS and runs[i][2] - d >= MIN_BARS:
                runs[i - 1][2] += d
                runs[i][1] += d
                runs[i][2] -= d
    out: list[dict] = []
    for i, (s, b0, nb) in enumerate(runs):
        first_run, last_run = i == 0, i == len(runs) - 1
        nxt = runs[i + 1][0] if not last_run else None
        if s == 2:
            kind = "drop"
        elif s == 0:
            kind = "intro" if first_run else ("outro" if last_run else ("build" if nxt == 2 else "breakdown"))
        else:
            kind = "intro" if first_run else ("outro" if last_run else ("build" if nxt == 2 else "groove"))
        # a long quiet stretch before a drop: breakdown first, the last 8 bars are the build
        if s < 2 and not first_run and nxt == 2 and nb >= 12:
            out.append({"kind": "breakdown", "bar0": b0, "bars": nb - CHUNK_BARS})
            out.append({"kind": "build", "bar0": b0 + nb - CHUNK_BARS, "bars": CHUNK_BARS})
            continue
        # long stretches are cut at phrase length so the picture keeps moving with the music
        cuts = [0]
        if (nb >= 12) if kind in ("intro", "outro") else (nb > LONG_BARS):
            k = CHUNK_BARS
            while nb - k >= MIN_BARS:
                cuts.append(k)
                k += CHUNK_BARS
        for j, c in enumerate(cuts):
            end = cuts[j + 1] if j + 1 < len(cuts) else nb
            out.append({"kind": kind, "bar0": b0 + c, "bars": end - c})
    t_bar = lambda b: offset + (first + 4 * b) * beat           # noqa: E731  seconds of bar b
    res = []
    for i, sc in enumerate(out):
        start = 0.0 if i == 0 else t_bar(sc["bar0"])
        end = duration if i == len(out) - 1 else t_bar(sc["bar0"] + sc["bars"])
        res.append({"start": round(start, 4), "end": round(end, 4), "kind": sc["kind"], "bars": sc["bars"]})
    # the variant counts up within a kind so two drops in a row never look the same
    seen: dict[str, int] = {}
    for sc in res:
        sc["variant"] = seen.get(sc["kind"], 0)
        seen[sc["kind"]] = sc["variant"] + 1
    return res
