"""Generative motion layer for the scene videos, drawn from the audio itself.

One RGBA frame per video frame, at half resolution (ffmpeg scales it up), laid over the scene
looks. Everything here is driven by the measured beat grid and the music's own spectrum:

* shockwaves: a ring leaves the centre on every kick of a drop or groove (bigger on the bar line)
* radial spectrum: the 72 bands as bars around a ring, breathing with the music
* oscilloscope: the real waveform bent into a circle
* particles: a field that bursts outward on kicks, rushes inward during builds, drifts in breakdowns
* riser: converging lines and a rising bar through a build, the last beats of a drop get a strobe
* bottom bars: the spectrum, as before

Colours come from the song's accent with a small, fixed shift, so a song keeps its own palette.
Random numbers are seeded: a render is repeatable.
"""
from __future__ import annotations

import colorsys

import numpy as np

from . import viz
from .audio import SR

PULSE_DECAY = 5.0


def _rgb(accent_rgb: tuple[int, int, int], dh: float) -> np.ndarray:
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in accent_rgb))
    r, g, b = colorsys.hsv_to_rgb((h + dh) % 1.0, s, max(v, 0.9))
    return np.array([r, g, b], dtype=np.float32) * 255


class Layer:
    def __init__(self, W: int, H: int, bpm: float, offset: float, rgb: tuple[int, int, int], secs: list[dict],
                 mono: np.ndarray, fps: int, n_frames: int, base: int):
        self.w, self.h = W // 2, H // 2
        self.bpm, self.offset, self.fps = bpm, offset, fps
        self.beat = 60.0 / bpm
        self.secs = secs
        self.mono = mono.astype(np.float32)
        self.levels = viz.band_levels(self.mono, fps, n_frames)
        self.base = base // 2
        yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
        self.cx, self.cy = self.w / 2, self.h * (0.5 if W > H else 0.46)
        self.R = np.hypot(xx - self.cx, yy - self.cy)
        self.scale = float(min(self.w, self.h))
        rng = np.random.default_rng(7)
        n = 420
        self.pa = rng.uniform(0, 2 * np.pi, n).astype(np.float32)
        self.pr = rng.uniform(0.05, 1.0, n).astype(np.float32)
        self.pv = rng.uniform(0.4, 1.0, n).astype(np.float32)
        self.pb = rng.uniform(0.5, 1.0, n).astype(np.float32)
        self._q: list = []
        self.pal = {"main": _rgb(rgb, 0.0), "warm": _rgb(rgb, -0.04), "cool": _rgb(rgb, 0.06), "alt": _rgb(rgb, 0.5)}

    def section(self, t: float) -> dict:
        for s in self.secs:
            if s["start"] <= t < s["end"]:
                return s
        return self.secs[-1]

    def _splat(self, acc: np.ndarray, xs, ys, col: np.ndarray, amp, size: int = 1) -> None:
        """Queue points; ``flush`` adds them all with one bincount per channel."""
        xi, yi = np.round(xs).astype(int), np.round(ys).astype(int)
        amp = np.broadcast_to(np.asarray(amp, dtype=np.float32), xi.shape)
        for dy in range(-size, size + 1):
            for dx in range(-size, size + 1):
                ok = (xi + dx >= 0) & (xi + dx < self.w) & (yi + dy >= 0) & (yi + dy < self.h)
                if ok.any():
                    self._q.append(((yi[ok] + dy) * self.w + (xi[ok] + dx), amp[ok][:, None] * col[None, :]))

    def _flush(self, acc: np.ndarray) -> None:
        if not self._q:
            return
        idx = np.concatenate([q[0] for q in self._q])
        w = np.concatenate([q[1] for q in self._q])
        n = self.h * self.w
        for c in range(3):
            acc[..., c] += np.bincount(idx, weights=w[:, c], minlength=n).astype(np.float32).reshape(self.h, self.w)
        self._q = []

    def frame(self, k: int) -> bytes:
        t = k / self.fps
        sc = self.section(t)
        kind = sc["kind"]
        ph = (t - self.offset) / self.beat
        frac = ph - np.floor(ph)
        beat_i = int(np.floor(ph))
        p = float(np.exp(-PULSE_DECAY * frac))
        step = (beat_i + 1.0 - (1.0 - frac) ** 4) * self.beat     # time, advanced in surges that land on the kick
        lv = self.levels[min(k, len(self.levels) - 1)]
        acc = np.zeros((self.h, self.w, 3), dtype=np.float32)
        S = self.scale
        main, alt = self.pal["main"], self.pal["alt"]
        sec_t = (t - sc["start"]) / max(0.1, sc["end"] - sc["start"])
        hit = kind in ("drop", "groove")

        if hit or kind == "build":                      # shockwaves from the last three beats
            for back in range(3):
                age = (frac + back) * self.beat
                strong = ((beat_i - back) % 4) == 0
                r = (0.08 + age * (1.15 if strong else 0.8)) * S * 0.9
                w = (0.03 if strong else 0.018) * S + age * 0.02 * S
                fade = np.exp(-age * (2.2 if strong else 3.4)) * (1.0 if hit else 0.45)
                ring = np.exp(-((self.R - r) / w) ** 2) * fade * (1.0 if strong else 0.7)
                acc += ring[..., None] * (alt if strong and hit else main) * 1.9

        if kind != "intro" or sec_t > 0.5:             # radial spectrum
            n = len(lv)
            ang = np.arange(n) * 2 * np.pi / n + (step * 0.12 if kind != "build" else t * (0.12 + 0.5 * sec_t))
            r0 = S * (0.24 + 0.03 * p)
            length = S * 0.30 * lv ** 1.0 * (1.3 if hit else 0.8)
            for f in np.linspace(0, 1, 14):
                rr = r0 + length * f
                self._splat(acc, self.cx + np.cos(ang) * rr, self.cy + np.sin(ang) * rr, main * (0.6 + 0.9 * f), 1.0, 2)
            acc += (np.exp(-((self.R - r0) / (S * 0.010)) ** 2))[..., None] * main * 1.4

        i0 = int(t * SR)                                # oscilloscope ring
        seg = self.mono[i0:i0 + 2048]
        if len(seg) >= 2048:
            seg = seg[::4][:512]
            m = 360
            wave = np.interp(np.linspace(0, len(seg) - 1, m), np.arange(len(seg)), seg)
            wave = wave / (np.abs(wave).max() + 1e-6)
            th = np.linspace(0, 2 * np.pi, m, endpoint=False)
            rr = S * (0.15 + 0.012 * p) + wave * S * 0.055
            self._splat(acc, self.cx + np.cos(th) * rr, self.cy + np.sin(th) * rr, self.pal["cool"] * 1.0, 1.0, 2)

        if kind == "build":                             # particles
            rad = (self.pr * (1.0 - sec_t * 0.85) ** 1.2) * S * 0.95
            ang_p = self.pa + t * 0.8 * (0.6 + 1.6 * sec_t) * self.pv
            amp = 0.75 + 0.25 * self.pb
        elif hit:
            rad = ((self.pr + (1.0 - np.exp(-3.0 * frac)) * 0.9 * self.pv) % 1.2) * S * 0.9
            ang_p = self.pa + step * 0.15 * self.pv
            amp = (0.7 + 0.3 * self.pb) * (0.6 + 0.8 * p)
        else:
            rad = (self.pr + 0.02 * np.sin(t * 0.4 + self.pa)) * S * 0.9
            ang_p = self.pa + t * 0.05 * self.pv
            amp = 0.5 + 0.2 * self.pb
        self._splat(acc, self.cx + np.cos(ang_p) * rad * 1.35, self.cy + np.sin(ang_p) * rad, self.pal["warm"], amp * 1.4, 1)

        if kind == "build":                             # rising bar and converging lines
            acc[self.h - self.base - 6:self.h - self.base - 2, :int(self.w * sec_t)] += alt * 0.9
            for j in range(28):
                a = j * 2 * np.pi / 28 + t * 0.3
                for f in (0.55, 0.7, 0.85):
                    rr = S * (1.0 - f * sec_t) * f * 1.2
                    self._splat(acc, np.array([self.cx + np.cos(a) * rr]), np.array([self.cy + np.sin(a) * rr]),
                                alt, 0.6 * sec_t, 0)
        self._flush(acc)
        if kind == "drop" and beat_i % 4 == 0 and p > 0.6:
            acc += 0.22 * main

        n = len(lv)                                     # bottom spectrum
        gap = 2
        bw = max(1, int((self.w * 0.94) / n) - gap)
        x0 = (self.w - n * (bw + gap)) // 2
        for i, val in enumerate(lv):
            hh = max(2, int(val * self.base))
            x = x0 + i * (bw + gap)
            acc[self.h - hh - 4:self.h - 4, x:x + bw] += main * 1.1
            acc[self.h - hh - 4:self.h - hh - 2, x:x + bw] += 120

        out = np.empty((self.h, self.w, 4), dtype=np.uint8)
        out[..., :3] = np.clip(acc, 0, 255).astype(np.uint8)
        out[..., 3] = (np.clip(acc.max(axis=2) / 140.0, 0, 1) * 255).astype(np.uint8)
        return out.tobytes()


def frames(mono: np.ndarray, fps: int, n_frames: int, W: int, H: int, rgb: tuple[int, int, int],
           secs: list[dict], bpm: float, offset: float, base: int):
    layer = Layer(W, H, bpm, offset, rgb, secs, mono, fps, n_frames, base)
    for k in range(n_frames):
        yield layer.frame(k)
