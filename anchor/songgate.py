"""The song gate: does a take measure like a real song, or like a loop or a texture?

Anchit, 2026-10-11, on Transmit Spiral: "atrocious song - it is not even like a song - ensure
everything sounds perfectly like a song". Anchit, 2026-10-24: a hard gate, only songs that pass
go out, even if a day then gets fewer than two.

The limits come from Anchit's own nine Suno songs released as drops between 2026-09-04 and
2026-09-14 (Then Do It, Silent Transmission, Stay With Me, Robot Love, Where It Begins,
Let's F*cking Go!, Signal Detected, Project Mayhem, Crossing The Threshold). Each limit is the
weakest value any of those nine songs has, loosened by 10 percent of their spread. A take must
pass every check. Measured 2026-10-11: all 9 Suno songs pass, all 16 ACE-Step drops then out
fail; measured 2026-10-24: the six engine drops of 10-16 to 10-24 fail too.

``measure`` and ``judge`` are the daily publish check's gate (Anchit's anchor-at Project doc
claude/anchor-song-gate.py, sha256 12e57c6e...) line for line, so the robot and the check that
watches it give the same verdict on the same file. librosa is imported only when a file is
measured: the rest of the robot runs without it.
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np

# name: (direction, limit, plain-English failure, unit)
CHECKS = {
    "noise_score": ("max", 0.0462, "sounds like noise more than notes", ""),
    "melody_share": ("min", 0.7937, "too little melody and harmony under the drums", ""),
    "sound_movement": ("min", 0.1296, "the sound barely changes from start to end", ""),
    "loud_quiet_range_db": ("min", 6.76, "no real drops or quiet parts", " dB"),
    "most_different_parts": ("max", -0.2545, "no part sounds different from the rest (one loop start to finish)", ""),
    "section_changes": ("min", 7.1, "too few section changes", ""),
    "silent_tail_s": ("max", 3.0, "ends in dead air", " s"),
}
REFERENCE = {  # the nine Suno songs: weakest and strongest value
    "noise_score": (0.0156, 0.0434),
    "melody_share": (0.805, 0.918),
    "sound_movement": (0.157, 0.431),
    "loud_quiet_range_db": (7.4, 13.8),
    "most_different_parts": (-0.502, -0.277),
    "section_changes": (8, 17),
    "silent_tail_s": (0.0, 2.2),
}


def enabled() -> bool:
    """On unless ANCHOR_SONG_GATE is 0/off (the tests switch it off; their engine is a test tone)."""
    return (os.environ.get("ANCHOR_SONG_GATE") or "1").lower() not in ("0", "off", "false", "no")


def _checkerboard(n):
    import scipy.signal as ss
    g = np.outer(ss.windows.gaussian(2 * n, n / 2), ss.windows.gaussian(2 * n, n / 2))
    sign = np.ones((2 * n, 2 * n))
    sign[:n, n:] = -1
    sign[n:, :n] = -1
    return g * sign


def measure(path):
    import librosa
    import scipy.signal as ss
    warnings.filterwarnings("ignore")
    y, sr = librosa.load(path, sr=22050, mono=True)
    if len(y) < sr * 20:
        raise ValueError("shorter than 20 s")
    hop = 512
    m = {"duration_s": round(len(y) / sr, 1)}

    # loud vs quiet parts, 2 s windows every second, lightly smoothed
    win = 2 * sr
    rms = np.array([np.sqrt(np.mean(y[i:i + win] ** 2) + 1e-12) for i in range(0, len(y) - win, sr)])
    rdb = np.convolve(20 * np.log10(rms + 1e-9), np.ones(3) / 3, mode="same")
    m["loud_quiet_range_db"] = round(float(np.percentile(rdb, 95) - np.percentile(rdb, 10)), 2)

    # noise vs notes
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
    m["noise_score"] = round(float(np.mean(librosa.feature.spectral_flatness(S=S)[0])), 4)
    H, P = librosa.decompose.hpss(S)
    m["melody_share"] = round(float((H ** 2).sum() / ((H ** 2).sum() + (P ** 2).sum() + 1e-12)), 3)

    # brightness movement over 4 s spans
    cen = librosa.feature.spectral_centroid(S=S, sr=sr)[0]
    k = int(4 * sr / hop)
    cs = np.convolve(cen, np.ones(k) / k, mode="valid")
    m["sound_movement"] = round(float(np.std(cs) / (np.mean(cs) + 1e-9)), 3)

    # arrangement on bars: how different the parts are, how often a new section starts
    yh = librosa.istft(H, hop_length=hop, length=len(y))
    chroma = librosa.feature.chroma_cqt(y=yh, sr=sr, hop_length=hop)
    mf = librosa.feature.mfcc(y=y, sr=sr, hop_length=hop, n_mfcc=13)
    feat = np.vstack([librosa.util.normalize(chroma, axis=0),
                      (mf - mf.mean(axis=1, keepdims=True)) / (mf.std(axis=1, keepdims=True) + 1e-9)])
    oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    _, beats = librosa.beat.beat_track(onset_envelope=oenv, sr=sr, hop_length=hop)
    if len(beats) > 16:
        bf = librosa.util.sync(feat, beats[::4], aggregate=np.median)
        bf = bf / (np.linalg.norm(bf, axis=0, keepdims=True) + 1e-9)
        ssm = bf.T @ bf
        n = ssm.shape[0]
        kk = 4
        pad = np.pad(ssm, kk, mode="edge")
        kern = _checkerboard(kk)
        nov = np.maximum(np.array([np.sum(pad[i:i + 2 * kk, i:i + 2 * kk] * kern) for i in range(n)]), 0)
        if nov.max() > 0:
            nov = nov / nov.max()
        peaks, _ = ss.find_peaks(nov, height=0.3, distance=4)
        m["section_changes"] = int(len(peaks) + 1)
        m["most_different_parts"] = round(float(np.percentile(ssm[np.triu_indices(n, 1)], 5)), 3)
    else:
        m["section_changes"] = 0
        m["most_different_parts"] = 1.0

    # dead air at the end
    fr = 20 * np.log10(librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0] + 1e-9)
    loud = np.where(fr > -50)[0]
    m["silent_tail_s"] = round(float((len(fr) - 1 - loud[-1]) * hop / sr) if len(loud) else len(y) / sr, 1)
    return m


def judge(m):
    fails = []
    for name, (direction, limit, words, unit) in CHECKS.items():
        v = m[name]
        bad = v < limit if direction == "min" else v > limit
        if bad:
            lo, hi = REFERENCE[name]
            fails.append({"check": name, "value": v, "limit": limit, "why": words,
                          "songs_range": [lo, hi], "unit": unit.strip()})
    return fails


def score(m: dict) -> float:
    """How far a take sits on the good side of the limits, in units of the spread of Anchit's own
    songs, averaged over the checks (0 at the limits, about 1 in the middle of his songs,
    negative when it fails). The robot keeps the passing take with the highest score."""
    total, n = 0.0, 0
    for name, (direction, limit, _words, _unit) in CHECKS.items():
        if m.get(name) is None:
            continue
        lo, hi = REFERENCE[name]
        spread = max(abs(hi - lo), 1e-9)
        margin = (m[name] - limit) if direction == "min" else (limit - m[name])
        total += max(-3.0, min(3.0, margin / spread))
        n += 1
    return round(total / n, 4) if n else 0.0


def check(path: Path | str) -> dict:
    """The verdict on one file: {"verdict": PASS/FAIL, "measures": {...}, "fails": [...]}."""
    m = measure(str(path))
    fails = judge(m)
    return {"verdict": "FAIL" if fails else "PASS", "measures": m, "fails": fails}


def reasons(result: dict) -> list[str]:
    """The fails as short lines for logs, the run summary and the status page."""
    return [f"{f['why']} ({f['check']} {f['value']}{(' ' + f['unit']) if f['unit'] else ''}, "
            f"limit {f['limit']})" for f in (result or {}).get("fails", [])]


def main(argv: list[str]) -> int:
    """python -m anchor.songgate FILE... [--json]: the same report as the publish check's script."""
    as_json = "--json" in argv
    paths = [a for a in argv if a != "--json"]
    if not paths:
        print(__doc__)
        return 2
    worst = 0
    for p in paths:
        try:
            r = check(p)
        except Exception as exc:          # noqa: BLE001 - unreadable or too short
            print(json.dumps({"file": p, "verdict": "ERROR", "error": str(exc)}) if as_json else f"ERROR  {p}: {exc}")
            worst = max(worst, 2)
            continue
        worst = max(worst, 0 if r["verdict"] == "PASS" else 1)
        if as_json:
            print(json.dumps({"file": p, **r}), flush=True)
        else:
            print(f"{r['verdict']}  {p}  ({r['measures']['duration_s']} s)")
            for line in reasons(r):
                print(f"   - {line}")
    return worst


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
