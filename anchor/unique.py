"""Nothing goes out twice: a cover, a title or a track that resembles one already released
is sent back for another seed. Every check here is measured, not guessed.

Cover art: a 16x16 perceptual hash (DCT of the greyscale thumbnail) plus a difference hash,
compared bit for bit. Two covers drawn from the same motif land under 70 of 256; the
catalogue's own near-duplicates (the three orange chevron stacks) scored 56 and 74.

Audio, two prints of every released master, both cross-correlated over a lag window:
the loudness envelope at 100 ms (identical recordings 1.00, the same record shifted or
regained 1.00, unrelated techno 0.0-0.5) and the spectral sequence, 24 log-spaced bands
every 0.5 s, z-scored per band (the same record 0.86 after a shift and a gain change,
unrelated records 0.0-0.65 across the catalogue on 2026-09-23, the top pair being two acid
tracks cut to the same arrangement). Either print over its limit sends the take back for
another seed. Timbre alone (band means) is useless here: every record on the channel is a
distorted kick and a sub, and they all correlate above 0.75.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

COVER_MIN_DISTANCE = 84       # of 256; below this the motif is the same one
AUDIO_MAX_SIMILARITY = 0.80   # envelope correlation above this is the same record
SEQUENCE_MAX_SIMILARITY = 0.75   # spectral-sequence correlation above this is the same record and sound
SR = 48_000


# --------------------------------------------------------------------------- images
def _dct2(a: np.ndarray) -> np.ndarray:
    n = a.shape[0]
    k = np.arange(n)
    c = np.cos(np.pi * (2 * k[None, :] + 1) * k[:, None] / (2 * n))
    return c @ a @ c.T


def phash(img: Image.Image, size: int = 16) -> np.ndarray:
    g = np.asarray(img.convert("L").resize((size * 4, size * 4), Image.LANCZOS), dtype=np.float64)
    low = _dct2(g)[:size, :size]
    return (low > np.median(low)).ravel()


def dhash(img: Image.Image, size: int = 16) -> np.ndarray:
    g = np.asarray(img.convert("L").resize((size + 1, size), Image.LANCZOS), dtype=np.float64)
    return (g[:, 1:] > g[:, :-1]).ravel()


def cover_distance(a: Image.Image | Path, b: Image.Image | Path) -> float:
    ia = Image.open(a) if isinstance(a, (str, Path)) else a
    ib = Image.open(b) if isinstance(b, (str, Path)) else b
    return float((np.count_nonzero(phash(ia) != phash(ib)) + np.count_nonzero(dhash(ia) != dhash(ib))) / 2)


def nearest_cover(candidate: Image.Image | Path, covers_dir: Path) -> tuple[float, str | None]:
    best = (999.0, None)
    for f in sorted(Path(covers_dir).glob("*.jpg")):
        try:
            d = cover_distance(candidate, f)
        except OSError:
            continue
        if d < best[0]:
            best = (d, f.stem)
    return best


# ---------------------------------------------------------------------------- audio
def envelope(mono: np.ndarray, sr: int, hop_s: float = 0.1) -> np.ndarray:
    hop = max(1, int(sr * hop_s))
    n = len(mono) // hop
    if n < 4:
        return np.zeros(4)
    e = np.sqrt((mono[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    e = e - e.mean()
    return e / (np.linalg.norm(e) or 1.0)


def audio_similarity(env_a: np.ndarray, env_b: np.ndarray, max_lag_s: float = 8.0, hop_s: float = 0.1) -> float:
    """Peak normalised cross-correlation over a small lag window (both are 4/4 at ~150 BPM)."""
    n = min(len(env_a), len(env_b))
    a, b = env_a[:n], env_b[:n]
    lag = int(max_lag_s / hop_s)
    best = 0.0
    for k in range(-lag, lag + 1):
        if k >= 0:
            x, y = a[k:], b[: n - k]
        else:
            x, y = a[: n + k], b[-k:]
        if len(x) < 10:
            continue
        best = max(best, float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) or 1.0)))
    return best


def band_sequence(mono: np.ndarray, sr: int = SR, n_fft: int = 2048, hop_s: float = 0.5, n_bands: int = 24,
                  lo: float = 40.0, hi: float = 16000.0) -> np.ndarray:
    """Log energy in ``n_bands`` log-spaced bands every ``hop_s``: (frames, bands). The
    record's sound over time, which is what two takes of one prompt share and two records do not."""
    hop = max(1, int(sr * hop_s))
    win = np.hanning(n_fft)
    edges = np.geomspace(lo, min(hi, sr / 2 - 1), n_bands + 1)
    idx = np.searchsorted(np.fft.rfftfreq(n_fft, 1 / sr), edges)
    rows = []
    for s in range(0, len(mono) - n_fft, hop):
        spec = np.abs(np.fft.rfft(mono[s:s + n_fft] * win)) ** 2
        rows.append([np.log10(spec[idx[i]:idx[i + 1]].sum() + 1e-9) for i in range(n_bands)])
    return np.array(rows) if rows else np.zeros((4, n_bands))


def sequence_similarity(seq_a: np.ndarray, seq_b: np.ndarray, max_lag_s: float = 8.0, hop_s: float = 0.5) -> float:
    """Mean per-band correlation of the z-scored sequences, best over a small lag window."""
    n = min(len(seq_a), len(seq_b))
    a, b = seq_a[:n], seq_b[:n]
    a = (a - a.mean(axis=0)) / (a.std(axis=0) + 1e-9)
    b = (b - b.mean(axis=0)) / (b.std(axis=0) + 1e-9)
    lag = int(max_lag_s / hop_s)
    best = 0.0
    for k in range(-lag, lag + 1):
        x, y = (a[k:], b[: n - k]) if k >= 0 else (a[: n + k], b[-k:])
        if len(x) < 10:
            continue
        best = max(best, float((x * y).mean()))
    return best


def prints(mono: np.ndarray, sr: int = SR) -> dict[str, np.ndarray]:
    return {"env": envelope(mono, sr), "seq": band_sequence(mono, sr)}


def similarity(a: dict, b: dict) -> dict[str, float]:
    return {"envelope": audio_similarity(a["env"], b["env"]), "sequence": sequence_similarity(a["seq"], b["seq"])}


def is_same_record(score: dict) -> bool:
    return score["envelope"] > AUDIO_MAX_SIMILARITY or score["sequence"] > SEQUENCE_MAX_SIMILARITY


def released_prints(catalog_path: Path, work: Path, limit: int = 40) -> dict[str, dict]:
    """Prints of the released masters (cached as .npz next to the build)."""
    from .audio import decode
    work.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict] = {}
    try:
        drops = json.loads(Path(catalog_path).read_text()).get("drops", [])[:limit]
    except (OSError, ValueError):
        return out
    for d in drops:
        url, did = d.get("audio_url"), d.get("id")
        if not (url and did):
            continue
        key = did + (f"-v{url.split('?v=', 1)[1]}" if "?v=" in url else "")      # a new master is printed again
        npz = work / f"{key}.npz"
        if npz.exists():
            with np.load(npz) as z:
                out[did] = {"env": z["env"], "seq": z["seq"]}
            continue
        mp3 = work / f"{key}.mp3"
        try:
            if not mp3.exists():
                urllib.request.urlretrieve(url, mp3)
            pr = prints(decode(mp3).mean(axis=1))
        except Exception:      # noqa: BLE001 - a missing release must not block the drop
            continue
        np.savez(npz, **pr)
        out[did] = pr
    return out


def check_audio(wav: Path, catalog_path: Path, work: Path) -> tuple[float, str | None, dict]:
    """(worst score, the release it is nearest to, both scores for that release).

    The worst score is the larger of the two prints' correlations so that one number still
    answers "how close did this come"; the dict says which print said so."""
    from .audio import decode
    mine = prints(decode(wav).mean(axis=1))
    worst: tuple[float, str | None, dict] = (0.0, None, {"envelope": 0.0, "sequence": 0.0})
    for did, pr in released_prints(catalog_path, work).items():
        score = similarity(mine, pr)
        if max(score.values()) > worst[0]:
            worst = (max(score.values()), did, score)
    return worst
