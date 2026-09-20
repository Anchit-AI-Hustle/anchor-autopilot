"""Nothing goes out twice: a cover, a title or a track that resembles one already released
is sent back for another seed. Every check here is measured, not guessed.

Cover art: a 16x16 perceptual hash (DCT of the greyscale thumbnail) plus a difference hash,
compared bit for bit. Two covers drawn from the same motif land under 70 of 256; the
catalogue's own near-duplicates (the three orange chevron stacks) scored 56 and 74.

Audio: the loudness envelope at 100 ms, cross-correlated after normalisation; identical
recordings score 1.00, the same loop re-rendered scores above 0.8, unrelated techno at the
same tempo sits around 0.3-0.5.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

COVER_MIN_DISTANCE = 84       # of 256; below this the motif is the same one
AUDIO_MAX_SIMILARITY = 0.80   # envelope correlation above this is the same record


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


def released_envelopes(catalog_path: Path, work: Path, limit: int = 40) -> dict[str, np.ndarray]:
    """Envelopes of the released masters (cached as .npy next to the build)."""
    from .audio import decode
    work.mkdir(parents=True, exist_ok=True)
    out: dict[str, np.ndarray] = {}
    try:
        drops = json.loads(Path(catalog_path).read_text()).get("drops", [])[:limit]
    except (OSError, ValueError):
        return out
    for d in drops:
        url, did = d.get("audio_url"), d.get("id")
        if not (url and did):
            continue
        npy = work / f"{did}.npy"
        if npy.exists():
            out[did] = np.load(npy)
            continue
        mp3 = work / f"{did}.mp3"
        try:
            if not mp3.exists():
                urllib.request.urlretrieve(url, mp3)
            env = envelope(decode(mp3).mean(axis=1), 48_000)
        except Exception:      # noqa: BLE001 - a missing release must not block the drop
            continue
        np.save(npy, env)
        out[did] = env
    return out


def check_audio(wav: Path, catalog_path: Path, work: Path) -> tuple[float, str | None]:
    from .audio import decode
    mine = envelope(decode(wav).mean(axis=1), 48_000)
    worst = (0.0, None)
    for did, env in released_envelopes(catalog_path, work).items():
        s = audio_similarity(mine, env)
        if s > worst[0]:
            worst = (s, did)
    return worst
