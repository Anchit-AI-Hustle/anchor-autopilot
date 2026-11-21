"""Album art drawn from the song itself (Anchit, 2026-11-21: "ensure all youtube upload thumbnails
are unique in their own way as per the music and the vibe of each song - ensure no duplicacy or
repetition ever - album art must be original and unique and music based only").

Before, every cover was one of six fixed procedural motifs (art.procedural) and the song gate's
cover check logged "too close" on all five redraws. Here the picture is measured from the master:

- the bars: one ring, ridge or beam per bar, sized by that bar's loudness (the arrangement you hear)
- the spectrum over time: a 48-band mel picture of the whole song
- the 303 / lead line: the spectral centroid curve, drawn as a resonant line
- the voice: energy in the 1 to 4 kHz band, for the rap halftone
- the key: the strongest pitch class sets the hue, minor darker than major

Each decided genre has its own visual language (artist/genres.toml "visual"), and a mashup layers its
two genres: the first draws the ground, the second the figure over it. Every song is different audio,
so every picture is different; ``variant`` turns and re-colours it when a cover still comes too close
to one already out (anchor/unique.py).
"""
from __future__ import annotations

import colorsys
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SR = 22050
STYLES = ("hard_techno", "industrial_techno", "warehouse_techno", "acid_techno", "psychedelic_techno", "techno_rap")
# what each genre looks like (artist/genres.toml visual), as colour: (hue offset, saturation, value)
TINT = {"hard_techno": (0.0, 0.85, 0.95), "industrial_techno": (0.07, 0.35, 0.75),
        "warehouse_techno": (0.58, 0.25, 0.95), "acid_techno": (0.22, 0.95, 1.0),
        "psychedelic_techno": (0.0, 0.8, 1.0), "techno_rap": (0.12, 0.8, 1.0)}
GENRE_HUE = {"hard_techno": 0.0, "industrial_techno": 0.06, "warehouse_techno": 0.6, "acid_techno": 0.2,
             "techno_rap": 0.12}


def _stft(x: np.ndarray, n_fft: int = 2048, hop: int = 512) -> np.ndarray:
    """Magnitude spectrogram, numpy only (works on every runner, with or without librosa)."""
    if len(x) < n_fft:
        x = np.pad(x, (0, n_fft - len(x)))
    frames = 1 + (len(x) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(frames)[:, None]
    win = np.hanning(n_fft).astype(np.float32)
    return np.abs(np.fft.rfft(x[idx] * win, axis=1)).T.astype(np.float32)


def _mel_bands(sr: int, n_fft: int, n: int = 48, lo: float = 30.0, hi: float = 11000.0) -> np.ndarray:
    """Triangular mel filters (n x bins)."""
    mel = lambda f: 2595 * np.log10(1 + f / 700.0)
    inv = lambda m: 700 * (10 ** (m / 2595.0) - 1)
    edges = inv(np.linspace(mel(lo), mel(min(hi, sr / 2 - 1)), n + 2))
    f = np.fft.rfftfreq(n_fft, 1 / sr)
    fb = np.zeros((n, len(f)), np.float32)
    for i in range(n):
        a, b, c = edges[i], edges[i + 1], edges[i + 2]
        fb[i] = np.clip(np.minimum((f - a) / (b - a + 1e-9), (c - f) / (c - b + 1e-9)), 0, None)
    return fb


def features(audio: np.ndarray, sr: int, bpm: float) -> dict:
    """What the picture is made of, measured from the master (numpy only)."""
    mono = (audio.mean(axis=1) if audio.ndim == 2 else audio).astype(np.float32)
    step = max(1, int(round(sr / SR)))           # 48 kHz -> about 24 kHz, enough for a picture
    mono, sr = mono[::step], sr / step
    n_fft, hop = 2048, 512
    S = _stft(mono, n_fft, hop)
    f = np.fft.rfftfreq(n_fft, 1 / sr)
    mel = 10 * np.log10(_mel_bands(int(sr), n_fft) @ (S ** 2) + 1e-10)
    mel = np.clip(mel, mel.max() - 80, None)
    mel = (mel - mel.min()) / (np.ptp(mel) + 1e-9)
    rms = np.sqrt((S ** 2).mean(axis=0))
    fps = sr / hop
    bar_frames = max(1, int(round(4 * 60.0 / bpm * fps)))
    bars = np.array([rms[i:i + bar_frames].mean() for i in range(0, len(rms), bar_frames)])
    bars = bars / (bars.max() + 1e-9)
    cent = (f[:, None] * S).sum(axis=0) / (S.sum(axis=0) + 1e-9)
    cent = np.convolve(cent, np.ones(9) / 9, mode="same")
    cent = (cent - cent.min()) / (np.ptp(cent) + 1e-9)
    voice = S[(f > 1000) & (f < 4000)].mean(axis=0)
    voice = voice / (voice.max() + 1e-9)
    # pitch class of every bin from 55 Hz up, weighted by energy
    ok = f > 55
    pc = (np.round(12 * np.log2(f[ok] / 440.0)) + 9) % 12
    energy = (S[ok] ** 2).sum(axis=1)
    chroma = np.array([energy[pc == k].sum() for k in range(12)])
    rise = np.diff(np.convolve(bars, np.ones(2) / 2, mode="same"))
    drops = [int(i) for i in np.argsort(rise)[::-1][:4] if rise[i] > 0.12]
    return {"mel": mel, "bars": bars, "cent": cent, "voice": voice, "chroma": chroma,
            "key": int(np.argmax(chroma)), "drops": sorted(drops), "bpm": float(bpm)}


def palette(feat: dict, genres: tuple[str, ...], minor: bool, variant: int = 0) -> list[tuple[int, int, int]]:
    """Colours: each genre keeps its own colour (hard techno red, industrial rust and steel,
    warehouse cold white-blue, acid green, rap gold), the song's key moves it a little, and
    psychedelic takes the key's hue around the whole wheel. Minor keys are darker."""
    k = feat["key"] / 12.0
    out = []
    for i, g in enumerate(genres or ("hard_techno",)):
        _, s, v = TINT.get(g, (0.0, 0.7, 0.9))
        hue = (k + 0.137 * variant) % 1.0 if g == "psychedelic_techno" else \
            (GENRE_HUE.get(g, 0.0) + (k - 0.5) * 0.12 + 0.05 * variant) % 1.0
        v = v * (0.85 if minor else 1.0)
        for dh, ds, dv in ((0, 0, 0), (0.06, -0.2, -0.2), (-0.04, 0.05, -0.55)):
            r, gg, b = colorsys.hsv_to_rgb((hue + dh) % 1.0, min(1, max(0, s + ds)), min(1, max(0.05, v + dv)))
            out.append((int(r * 255), int(gg * 255), int(b * 255)))
    return out


def _ground(size, pal, dark=0.08):
    c = np.array(pal[2], dtype=np.float32) * dark
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) / size
    v = 1 - 0.6 * np.sqrt((xx - 0.5) ** 2 + (yy - 0.55) ** 2)
    arr = np.clip(c[None, None, :] * v[..., None] * 3 + 4, 0, 255)
    return Image.fromarray(arr.astype(np.uint8), "RGB").convert("RGBA")


def _rings(size, feat, pal, rot):
    """Hard techno: one ring per bar out from the centre, thickness and light from its loudness;
    strobe beams at the drops."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c, bars = size / 2, feat["bars"]
    n = len(bars)
    for i, e in enumerate(bars):
        r = size * 0.06 + size * 0.44 * (i / max(1, n - 1))
        w = max(1, int(1 + 9 * e ** 1.5))
        col = pal[0] if e > 0.75 else pal[1]
        d.ellipse([c - r, c - r, c + r, c + r], outline=(*col, int(60 + 190 * e)), width=w)
    for j, b in enumerate(feat["drops"] or [n // 2]):
        a = rot + 2 * math.pi * b / max(1, n)
        for k in (-1, 1):
            a2 = a + k * 0.035
            d.polygon([(c, c), (c + size * math.cos(a), c + size * math.sin(a)),
                       (c + size * math.cos(a2), c + size * math.sin(a2))], fill=(255, 255, 255, 70))
    return img


def _ridges(size, feat, pal, rot):
    """Industrial techno: the spectrum as stacked steel ridges, loud frames lifting the metal."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    mel = feat["mel"]
    cols = np.linspace(0, mel.shape[1] - 1, 240).astype(int)
    rows = 40
    for k in range(rows):
        band = mel[int(k * (mel.shape[0] - 1) / (rows - 1)), cols]
        band = np.convolve(band, np.ones(5) / 5, mode="same")
        y0 = size * (0.18 + 0.7 * k / rows)
        pts = [(size * 0.08 + size * 0.84 * i / (len(band) - 1), y0 - size * 0.09 * v ** 2) for i, v in enumerate(band)]
        shade = tuple(int(c * (0.10 + 0.25 * k / rows)) for c in pal[2])
        d.polygon([*pts, (size * 0.92, size), (size * 0.08, size)], fill=(*shade, 255))
        d.line(pts, fill=(*pal[0], 245), width=4)
    return img.rotate(math.degrees(rot) % 8 - 4, resample=Image.BICUBIC)


def _beams(size, feat, pal, rot):
    """Warehouse techno: a concrete room, light beams falling where the loudest bars are, haze."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    vx, vy = size * (0.5 + 0.12 * math.sin(rot)), size * 0.42
    for k in range(-9, 10):
        d.line([(vx, vy), (vx + k * size * 0.16, size)], fill=(*pal[2], 140), width=2)
    for y in np.geomspace(1, size - vy, 12):
        d.line([(0, vy + y), (size, vy + y)], fill=(*pal[2], 110), width=2)
    bars = feat["bars"]
    top = np.argsort(bars)[::-1][:7]
    for i in top:
        x = size * (0.06 + 0.88 * i / max(1, len(bars) - 1))
        w = size * (0.015 + 0.05 * bars[i])
        d.polygon([(x - w * 0.3, 0), (x + w * 0.3, 0), (vx + (x - vx) * 0.35 + w, size), (vx + (x - vx) * 0.35 - w, size)],
                  fill=(*pal[0], int(40 + 70 * bars[i])))
    return img.filter(ImageFilter.GaussianBlur(2))


def _acid(size, feat, pal, rot):
    """Acid techno: the song's own resonant line (spectral centroid), glowing, with its harmonics."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cent = feat["cent"]
    idx = np.linspace(0, len(cent) - 1, 900).astype(int)
    line = cent[idx]
    for h in range(5):
        amp = size * (0.22 - 0.035 * h)
        y0 = size * (0.5 + 0.06 * (h - 2)) + size * 0.03 * math.sin(rot + h)
        pts = [(size * 0.04 + size * 0.92 * i / (len(line) - 1),
                y0 + amp * (line[i] - 0.5) * math.sin(i / 37.0 + h + rot)) for i in range(len(line))]
        d.line(pts, fill=(*pal[h % 3], 230 - 35 * h), width=max(2, 10 - 2 * h))
    for i in np.argsort(line)[::-1][:6]:
        x, y = size * 0.04 + size * 0.92 * i / (len(line) - 1), size * 0.5
        r = size * 0.02 * (1 + line[i])
        d.ellipse([x - r, y - r, x + r, y + r], outline=(*pal[0], 220), width=4)
    glow = img.filter(ImageFilter.GaussianBlur(14))
    return Image.alpha_composite(glow, img)


def _kaleido(size, feat, pal, rot):
    """Psychedelic techno: the song's spectrum folded six ways around the centre."""
    mel = feat["mel"]
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    cx = cy = size / 2
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / (size * 0.5)
    a = (np.arctan2(yy - cy, xx - cx) + rot) % (math.pi / 3)
    a = np.minimum(a, math.pi / 3 - a) / (math.pi / 6)
    ti = np.clip((r * (mel.shape[1] - 1)).astype(int), 0, mel.shape[1] - 1)
    bi = np.clip((a * (mel.shape[0] - 1)).astype(int), 0, mel.shape[0] - 1)
    v = (mel[bi, ti] ** 0.55) * (r < 1)
    cols = np.array(pal[:3], dtype=np.float32)
    phase = (v * 2.999).astype(int)
    rgb = cols[np.clip(phase, 0, 2)] * (0.5 + 0.7 * v[..., None])
    alpha = (np.clip(v * 1.4, 0, 1) * 235).astype(np.uint8)
    rgba = np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), alpha])
    return Image.fromarray(rgba, "RGBA")


def _halftone(size, feat, pal, rot):
    """Techno rap: the voice as a halftone figure, read through the song along a tilted band:
    a dot only where words are, sized by how loud they are; slashes at the loudest lines."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    v = np.convolve(feat["voice"], np.ones(15) / 15, mode="same")
    n = 38
    idx = np.linspace(0, len(v) - 1, n * n).astype(int)
    field = v[idx].reshape(n, n)
    step = size / n
    tilt = math.tan(0.35 + 0.2 * math.sin(rot))
    for i in range(n):
        for j in range(n):
            e = field[i, j]
            band = abs((i - n / 2) - tilt * (j - n / 2)) < n * 0.22
            if e < 0.35 or not band:
                continue
            r = step * 0.62 * e
            x, y = (j + 0.5) * step, (i + 0.5) * step
            d.ellipse([x - r, y - r, x + r, y + r], fill=(*pal[0], int(150 + 100 * e)))
    for k in np.argsort(v[idx])[::-1][:2]:
        y = size * (k // n) / n
        d.polygon([(0, y), (size, y - size * 0.32), (size, y - size * 0.28), (0, y + size * 0.04)], fill=(*pal[0], 120))
    return img


DRAW = {"hard_techno": _rings, "industrial_techno": _ridges, "warehouse_techno": _beams,
        "acid_techno": _acid, "psychedelic_techno": _kaleido, "techno_rap": _halftone}


def render(feat: dict, genres: tuple[str, ...], minor: bool, size: int = 1440, variant: int = 0) -> Image.Image:
    """The picture: the first genre is the ground, the second the figure over it."""
    gs = tuple(g for g in genres if g in DRAW) or ("hard_techno",)
    # the voice is a figure over the music, never the ground
    gs = tuple(sorted(gs, key=lambda g: g == "techno_rap"))
    pal = palette(feat, gs, minor, variant)
    rot = 0.61 * variant + feat["key"] * 0.29
    img = _ground(size, pal)
    for i, g in enumerate(gs[:2]):
        layer = DRAW[g](size, feat, pal[3 * i:3 * i + 3] if len(pal) >= 3 * i + 3 else pal, rot)
        if i == 1:
            # the second genre sits over the first, a touch see-through so both are there
            arr = np.asarray(layer).copy()
            arr[..., 3] = (arr[..., 3] * 0.85).astype(np.uint8)
            layer = Image.fromarray(arr, "RGBA")
        img = Image.alpha_composite(img, layer)
    if variant % 2:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    return img.convert("RGB")
