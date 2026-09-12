"""Cover art: Cloudflare Workers AI (FLUX.1 schnell, free tier) with an in-house
procedural generator as fallback. Both are finished with ANCHOR typography."""
from __future__ import annotations

import base64
import io
import json
import math
import random
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .config import FONTS, Family, env
from .util import log

SIZE = 1440
CF_MODEL = "@cf/black-forest-labs/flux-1-schnell"
PROMPT_SUFFIX = ("album cover art, square composition, bold focal point, no text, no letters, "
                 "no words, no logo, no watermark, high detail, dramatic lighting")


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# --------------------------------------------------------------------------- AI art
def cloudflare_flux(prompt: str, seed: int, account_id: str, token: str, steps: int = 8,
                    timeout: int = 120) -> Image.Image:
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{CF_MODEL}"
    body = json.dumps({"prompt": prompt[:2048], "steps": steps, "seed": seed}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())
    if not payload.get("success", True) or "result" not in payload:
        raise RuntimeError(f"Cloudflare AI error: {payload.get('errors')}")
    img = Image.open(io.BytesIO(base64.b64decode(payload["result"]["image"]))).convert("RGB")
    if min(img.size) < 512:
        raise RuntimeError(f"Cloudflare AI returned a tiny image {img.size}")
    return img


# ------------------------------------------------------------------ procedural art
def _noise(rs: np.random.Generator, size: int, octaves: int = 5) -> np.ndarray:
    """Multi-octave value noise in [0, 1]."""
    acc = np.zeros((size, size), dtype=np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        cells = 4 * 2 ** o
        grid = rs.random((cells + 1, cells + 1)).astype(np.float32)
        img = Image.fromarray((grid * 255).astype(np.uint8)).resize((size, size), Image.BICUBIC)
        acc += amp * (np.asarray(img, dtype=np.float32) / 255.0)
        total += amp
        amp *= 0.5
    return acc / total


def _glow(layer: Image.Image, radius: int) -> Image.Image:
    return Image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius)), layer)


def _canvas(fam: Family, size: int, rs: np.random.Generator) -> Image.Image:
    bg = np.array(hex_rgb(fam.bg), dtype=np.float32)
    n = _noise(rs, size)[..., None]
    arr = np.clip(bg * (0.6 + 0.8 * n) + 6 * n, 0, 255)
    return Image.fromarray(arr.astype(np.uint8), "RGB").convert("RGBA")


def _radial(size: int, cx: float, cy: float, radius: float, colour, strength: float) -> Image.Image:
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / radius
    a = np.clip(1 - d, 0, 1) ** 2 * strength
    rgba = np.zeros((size, size, 4), dtype=np.float32)
    rgba[..., :3] = colour
    rgba[..., 3] = a * 255
    return Image.fromarray(rgba.astype(np.uint8), "RGBA")


def procedural(fam: Family, seed: int, size: int = SIZE) -> Image.Image:
    rs = np.random.default_rng(seed)
    r = random.Random(seed)
    img = _canvas(fam, size, rs)
    acc, acc2 = hex_rgb(fam.accent), hex_rgb(fam.accent2)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = size / 2

    if fam.id == "furnace":
        img = Image.alpha_composite(img, _radial(size, c, size * 0.95, size * 0.9, acc, 0.95))
        img = Image.alpha_composite(img, _radial(size, c, size * 0.9, size * 0.45, acc2, 0.7))
        for i in range(14):  # pipes
            x = r.uniform(0, size)
            w = r.uniform(size * 0.01, size * 0.035)
            d.rectangle([x, 0, x + w, size], fill=(*[int(v * 0.35) for v in acc], 150))
        for _ in range(500):  # sparks
            x, y = r.uniform(0, size), r.uniform(size * 0.2, size)
            ln = r.uniform(4, 40)
            d.line([x, y, x + r.uniform(-6, 6), y - ln], fill=(*acc2, r.randint(120, 255)), width=2)
        # faceless figure seen from behind: head, neck, sloped shoulders (position varies per drop)
        ink = (8, 6, 6, 255)
        cx, k, dy = c + size * r.uniform(-0.12, 0.12), r.uniform(0.85, 1.1), size * r.uniform(-0.04, 0.05)
        d.ellipse([cx - size * 0.085 * k, size * 0.47 + dy, cx + size * 0.085 * k, size * 0.66 + dy], fill=ink)
        d.rectangle([cx - size * 0.045 * k, size * 0.62 + dy, cx + size * 0.045 * k, size * 0.72 + dy], fill=ink)
        shoulders = [(cx - size * 0.36 * k, size * 0.8 + dy), (cx - size * 0.07 * k, size * 0.7 + dy),
                     (cx + size * 0.07 * k, size * 0.7 + dy), (cx + size * 0.36 * k, size * 0.8 + dy)]
        d.polygon([*shoulders, (cx + size * 0.42 * k, size), (cx - size * 0.42 * k, size)], fill=ink)
        d.line(shoulders, fill=(*acc, 200), width=4)  # rim light
    elif fam.id == "prism":
        for i in range(260):  # radial waveform rays
            ang = r.uniform(0, 2 * math.pi)
            r0, r1 = size * r.uniform(0.12, 0.22), size * r.uniform(0.28, 0.62)
            shade = r.randint(150, 255)
            d.line([c + r0 * math.cos(ang), c + r0 * math.sin(ang), c + r1 * math.cos(ang),
                    c + r1 * math.sin(ang)], fill=(shade, shade, shade, r.randint(60, 200)), width=r.randint(1, 4))
        for i in range(40):  # shattered crystal shards, irregular and asymmetric
            ang = r.uniform(0, 2 * math.pi)
            spread = r.uniform(0.05, 0.16)
            rr = size * r.uniform(0.06, 0.2)
            tip = rr * r.uniform(1.4, 2.6)
            hue = r.choice([0.52, 0.55, 0.6, 0.75, 0.83, 0.0])
            col = _hsv(hue, r.uniform(0.2, 0.8), 1.0)
            pts = [(c + r.uniform(-8, 8), c + r.uniform(-8, 8)),
                   (c + rr * math.cos(ang - spread), c + rr * math.sin(ang - spread)),
                   (c + tip * math.cos(ang + r.uniform(-0.05, 0.05)), c + tip * math.sin(ang + r.uniform(-0.05, 0.05))),
                   (c + rr * 0.8 * math.cos(ang + spread), c + rr * 0.8 * math.sin(ang + spread))]
            d.polygon(pts, fill=(*col, r.randint(120, 230)))
    elif fam.id == "rust":
        for k in range(46):  # spiral of blades and gear arcs
            t = k / 46
            rad = size * (0.06 + 0.42 * t)
            start = r.uniform(0, 360)
            col = acc if k % 3 else acc2
            d.arc([c - rad, c - rad, c + rad, c + rad], start, start + r.uniform(40, 200),
                  fill=(*col, 230), width=int(size * r.uniform(0.006, 0.02)))
            for tooth in range(r.randint(3, 9)):
                a = math.radians(start + tooth * 14)
                d.rectangle([c + rad * math.cos(a) - 6, c + rad * math.sin(a) - 6,
                             c + rad * math.cos(a) + 6, c + rad * math.sin(a) + 6], fill=(*col, 200))
        img = Image.alpha_composite(img, _radial(size, size * 0.85, size * 0.25, size * 0.6, (255, 240, 220), 0.35))
    elif fam.id == "chrome":
        for band in range(18):  # liquid metal bands
            amp = size * r.uniform(0.03, 0.09)
            freq = r.uniform(1.2, 3.2)
            phase = r.uniform(0, 2 * math.pi)
            y0 = size * (0.1 + band * 0.045)
            pts = [(x, y0 + amp * math.sin(freq * x / size * 2 * math.pi + phase)) for x in range(0, size + 8, 8)]
            shade = int(90 + 150 * (band % 5) / 4)
            col = (int(shade * 0.85), int(shade * 0.9), shade)
            d.line(pts, fill=(*col, 230), width=int(size * 0.02))
            d.line([(x, y - size * 0.006) for x, y in pts], fill=(*acc2, 140), width=3)
    elif fam.id == "void":
        img = Image.alpha_composite(img, _radial(size, c, 0, size * 1.1, (210, 210, 210), 0.35))
        beam = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        bd = ImageDraw.Draw(beam)
        bd.polygon([(c - size * 0.05, 0), (c + size * 0.05, 0), (c + size * 0.32, size), (c - size * 0.32, size)],
                   fill=(235, 235, 235, 70))
        img = Image.alpha_composite(img, beam.filter(ImageFilter.GaussianBlur(size // 40)))
        d.rectangle([c - size * 0.09, size * 0.28, c + size * 0.09, size * 0.95], fill=(10, 10, 10, 255))
        d.line([c + size * 0.09, size * 0.28, c + size * 0.09, size * 0.95], fill=(200, 200, 200, 180), width=3)
    else:  # volt and any future family: tunnel + lightning
        for k in range(12):
            inset = size * (0.04 + k * 0.035)
            d.rounded_rectangle([inset, inset, size - inset, size - inset], radius=int(size * 0.05),
                                outline=(*acc2, 40 + k * 8), width=2)
        for bolt in range(5):
            x, y = c + r.uniform(-size * 0.25, size * 0.25), 0.0
            pts = [(x, y)]
            while y < size:
                y += r.uniform(size * 0.02, size * 0.06)
                x += r.uniform(-size * 0.05, size * 0.05)
                pts.append((x, y))
            col = acc if bolt % 2 == 0 else acc2
            d.line(pts, fill=(*col, 255), width=r.randint(3, 7))
    img = Image.alpha_composite(img, _glow(layer, max(4, size // 120)))
    return img.convert("RGB")


def _hsv(h: float, s: float, v: float) -> tuple[int, int, int]:
    import colorsys
    rr, gg, bb = colorsys.hsv_to_rgb(h, s, v)
    return int(rr * 255), int(gg * 255), int(bb * 255)


# -------------------------------------------------------------------- finishing
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def finish(base: Image.Image, title: str, artist: str, fam: Family, seed: int, size: int = SIZE) -> Image.Image:
    """Grade the art and set the ANCHOR typography (title top, wordmark bottom)."""
    img = base.convert("RGB").resize((size, size), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(1.12)
    tint = Image.new("RGB", (size, size), hex_rgb(fam.accent))
    img = Image.blend(img, tint, 0.06)
    # legibility gradients
    grad = np.zeros((size, size, 4), dtype=np.uint8)
    ramp = np.linspace(1, 0, int(size * 0.34)) ** 1.6
    grad[: len(ramp), :, 3] = (ramp[:, None] * 190).astype(np.uint8)
    ramp2 = np.linspace(0, 1, int(size * 0.18)) ** 1.6
    grad[size - len(ramp2):, :, 3] = (ramp2[:, None] * 170).astype(np.uint8)
    img = Image.alpha_composite(img.convert("RGBA"), Image.fromarray(grad, "RGBA"))
    d = ImageDraw.Draw(img)
    text = title.upper()
    fsize = int(size * 0.17)
    font = _font("Anton.ttf", fsize)
    while d.textlength(text, font=font) > size * 0.86 and fsize > 40:
        fsize -= 4
        font = _font("Anton.ttf", fsize)
    tw = d.textlength(text, font=font)
    x, y = (size - tw) / 2, size * 0.055
    d.text((x + 4, y + 6), text, font=font, fill=(0, 0, 0, 170))
    d.text((x, y), text, font=font, fill=(*hex_rgb(fam.accent), 255) if fam.id not in ("void", "prism", "chrome")
           else (245, 245, 245, 255))
    mark = _font("JetBrainsMono-Bold.ttf", int(size * 0.034))
    d.text((size * 0.06, size * 0.915), "  ".join(artist.upper()), font=mark, fill=(240, 240, 240, 235))
    # film grain for a printed, non-plastic finish
    rs = np.random.default_rng(seed)
    grain = (rs.standard_normal((size, size)) * 7).astype(np.int16)
    arr = np.asarray(img.convert("RGB"), dtype=np.int16) + grain[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def make_cover(fam: Family, brief: dict, artist: str, out_dir: Path, mode: str | None = None) -> dict:
    """Write cover.jpg (1440), cover_1080.jpg (video) and cover_600.jpg (site). Returns metadata."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = mode or env("ANCHOR_ART", "auto")
    seed = int(brief["seed"]) % 2_147_483_647
    prompt = f"{fam.prompt}, {PROMPT_SUFFIX}"
    source, base, error = "procedural", None, None
    account, token = env("CF_ACCOUNT_ID"), env("CF_API_TOKEN")
    if mode in ("auto", "cloudflare") and account and token:
        for attempt in range(2):
            try:
                base = cloudflare_flux(prompt, seed + attempt, account, token)
                source = "cloudflare-flux-1-schnell"
                break
            except (urllib.error.URLError, RuntimeError, OSError, KeyError, ValueError) as exc:
                error = f"{type(exc).__name__}: {exc}"[:300]
                log(f"cover: Cloudflare attempt {attempt + 1} failed: {error}")
        if base is None and mode == "cloudflare":
            raise RuntimeError(f"Cloudflare cover generation failed: {error}")
    if base is None:
        base = procedural(fam, seed)
    base.save(out_dir / "cover_art_raw.jpg", quality=92)
    cover = finish(base, brief["title"], artist, fam, seed)
    cover.save(out_dir / "cover.jpg", quality=92)
    cover.resize((1080, 1080), Image.LANCZOS).save(out_dir / "cover_1080.jpg", quality=92)
    cover.resize((600, 600), Image.LANCZOS).save(out_dir / "cover_600.jpg", quality=85, optimize=True)
    return {"source": source, "prompt": prompt if source != "procedural" else None, "fallback_reason": error}


def og_card(cover: Path, title: str, meta_line: str, accent: str, out: Path, artist: str = "ANCHOR") -> None:
    """1200x630 social preview: cover left, title right."""
    w, h = 1200, 630
    card = Image.new("RGB", (w, h), (10, 10, 11))
    art = Image.open(cover).convert("RGB").resize((h, h), Image.LANCZOS)
    card.paste(art, (0, 0))
    d = ImageDraw.Draw(card)
    d.rectangle([h, 0, h + 8, h], fill=hex_rgb(accent))
    mark = _font("JetBrainsMono-Bold.ttf", 26)
    d.text((h + 48, 60), "  ".join(artist.upper()), font=mark, fill=(237, 237, 239))
    size = 92
    font = _font("Anton.ttf", size)
    words, lines = title.upper().split(), []
    while words:
        line = words.pop(0)
        while words and d.textlength(line + " " + words[0], font=font) <= w - h - 96:
            line += " " + words.pop(0)
        lines.append(line)
    y = 150
    for line in lines[:3]:
        d.text((h + 48, y), line, font=font, fill=hex_rgb(accent))
        y += size + 8
    small = _font("JetBrainsMono-Regular.ttf", 24)
    d.text((h + 48, y + 20), meta_line.upper(), font=small, fill=(200, 200, 205))
    d.text((h + 48, h - 70), "NEW TRACK EVERY DAY", font=small, fill=(163, 163, 171))
    card.save(out, quality=88, optimize=True)
