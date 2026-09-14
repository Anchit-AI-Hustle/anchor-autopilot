"""Redraw every published cover so that no two read as the same picture.

The guard that keeps new covers apart lives in the pipeline and only protects drops made
after it. The ten already on the site were drawn one motif per visual family — rust is
always gear arcs, furnace always pipes and sparks — so five rust drops came out as five
orange tiles. Measured at thumbnail size, the worst pair scored 7.8 out of 255.

Cover art is a pure function of the drop's seed, so the published ones can simply be redrawn
from the catalogue: no audio, no model, about a minute on a free runner. Two surfaces are
checked, because a viewer meets each song twice — the square cover on the website and the
9:16 tile on YouTube — and a drop has to differ from every earlier drop on BOTH.

Self-contained on purpose: it adds structure, framing and grading of its own on top of the
existing family art rather than requiring changes to anchor/, so it can run on the tree as
it stands today.

    python scripts/recover_covers.py [--dry-run]
"""
from __future__ import annotations

import argparse
import io
import itertools
import math
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from anchor import catalog                                        # noqa: E402
from anchor.art import SIZE, finish, hex_rgb, procedural          # noqa: E402
from anchor.config import CATALOG_PATH, SITE, load_profile        # noqa: E402
from anchor.util import log                                       # noqa: E402
from anchor.video import COVER, COVER_Y, H, W                     # noqa: E402

THUMB_GRID = 16
# Below this, two covers read as the same picture side by side. Calibrated on the first ten
# drops, where every same-family pair scored under 28 and the worst scored 7.8.
MIN_DISTANCE = 36.0
ATTEMPTS = 120


def structure(img: Image.Image, fam, seed: int) -> Image.Image:
    """Lay a seeded structural motif over the family art.

    A family is one motif and one palette, which is why its drops all look alike. This adds a
    second layer that differs in *shape*, not just colour — the thing a viewer actually reads
    at 200px — while leaving the family underneath recognisable.
    """
    r = random.Random(seed ^ 0x2545F491)
    size = img.width
    acc, acc2 = hex_rgb(fam.accent), hex_rgb(fam.accent2)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    kind = r.randint(0, 2)

    if kind == 0:                       # girder lattice: leaning beams, cross-ties, rivets
        lean = size * r.uniform(0.12, 0.45)
        for k in range(r.randint(9, 16)):
            x = r.uniform(-0.25, 1.0) * size
            w = size * r.uniform(0.025, 0.075)
            col = acc if k % 3 else acc2
            d.polygon([(x, 0), (x + w, 0), (x + w + lean, size), (x + lean, size)],
                      fill=(*col, r.randint(110, 215)))
        for _ in range(r.randint(5, 11)):
            y = r.uniform(0, 1) * size
            h = size * r.uniform(0.015, 0.055)
            d.rectangle([0, y, size, y + h], fill=(*acc2, r.randint(90, 185)))
        for _ in range(140):
            rx, ry, rr = r.uniform(0, size), r.uniform(0, size), size * r.uniform(0.004, 0.009)
            d.ellipse([rx - rr, ry - rr, rx + rr, ry + rr], fill=(*acc, r.randint(140, 230)))

    elif kind == 1:                     # one heavy off-centre gear throwing long spokes
        gx, gy = size / 2 + size * r.uniform(-0.3, 0.3), size / 2 + size * r.uniform(-0.3, 0.3)
        rad = size * r.uniform(0.26, 0.46)
        spokes = r.randint(9, 19)
        for k in range(spokes):
            a = 2 * math.pi * k / spokes + r.uniform(-0.06, 0.06)
            d.line([gx, gy, gx + rad * 2.4 * math.cos(a), gy + rad * 2.4 * math.sin(a)],
                   fill=(*acc2, 185), width=int(size * r.uniform(0.004, 0.013)))
        d.ellipse([gx - rad, gy - rad, gx + rad, gy + rad],
                  outline=(*acc, 240), width=int(size * r.uniform(0.02, 0.04)))
        for tooth in range(24):
            a = 2 * math.pi * tooth / 24
            tr = size * 0.022
            d.rectangle([gx + rad * math.cos(a) - tr, gy + rad * math.sin(a) - tr,
                         gx + rad * math.cos(a) + tr, gy + rad * math.sin(a) + tr], fill=(*acc, 215))
        hub = rad * r.uniform(0.16, 0.3)
        d.ellipse([gx - hub, gy - hub, gx + hub, gy + hub], fill=(*acc, 205))

    else:                               # hanging chains and hooks against the light
        ink = (8, 6, 6, 255)
        for _ in range(r.randint(7, 14)):
            x = r.uniform(0, size)
            drop_to = size * r.uniform(0.4, 0.85)
            w = int(size * r.uniform(0.006, 0.014))
            d.line([x, 0, x + r.uniform(-size * 0.03, size * 0.03), drop_to], fill=ink, width=w)
            link = size * r.uniform(0.012, 0.022)
            for yy in np.arange(0, drop_to, link * 2.2):
                d.ellipse([x - link, yy - link, x + link, yy + link], outline=ink, width=max(2, w // 2))
            hx = x + r.uniform(-size * 0.03, size * 0.03)
            d.arc([hx - link * 3, drop_to - link * 2, hx + link * 3, drop_to + link * 4],
                  200, 20, fill=ink, width=w + 2)

    glow = Image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(max(4, size // 120))), layer)
    return Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")


def framing(img: Image.Image, seed: int) -> Image.Image:
    """Move the camera: mirror, spin, push in, go off centre.

    A rotation needs sqrt(2) of zoom to keep the corners filled, so the floor is 1.45.
    """
    r = random.Random(seed ^ 0x5F3759DF)
    size = img.width
    if r.random() < 0.5:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    img = img.rotate(r.uniform(0, 360), resample=Image.BICUBIC)
    win = int(size / r.uniform(1.45, 2.15))
    slack = (size - win) // 2
    cx = size // 2 + int(r.uniform(-0.85, 0.85) * slack)
    cy = size // 2 + int(r.uniform(-0.85, 0.85) * slack)
    box = (cx - win // 2, cy - win // 2, cx - win // 2 + win, cy - win // 2 + win)
    return img.crop(box).resize((size, size), Image.LANCZOS)


def grade(img: Image.Image, seed: int, spread: float = 1.0) -> Image.Image:
    """Shift hue and weight away from the family default; `spread` widens on each retry."""
    r = random.Random(seed ^ 0x1B873593)
    h, sat, v = img.convert("HSV").split()
    shift = int(round(r.uniform(-30, 30) * spread / 360 * 255))
    h = h.point(lambda p: (p + shift) % 256)
    img = Image.merge("HSV", (h, sat, v)).convert("RGB")
    img = ImageEnhance.Color(img).enhance(1 + (r.uniform(0.82, 1.35) - 1) * spread)
    return ImageEnhance.Brightness(img).enhance(1 + (r.uniform(0.78, 1.20) - 1) * spread)


def published(img: Image.Image, quality: int = 92) -> Image.Image:
    """The image as it will exist on disk — the JPEG round-trip moves a tile by a point or two."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def tile(cover: Image.Image, seed: int) -> Image.Image:
    """What the cover becomes in a grid of Shorts: blurred backdrop plus the square inset.

    The backdrop is two thirds of the frame, so it is seeded too — a fixed treatment turns
    every drop in a family into the same tile however the cover itself is framed.
    """
    r = random.Random(seed ^ 0x9E3779B9)
    bg = cover.convert("RGB").resize((H, H), Image.LANCZOS)
    left = int((H - W) * r.uniform(0.1, 0.9))
    bg = bg.crop((left, 0, left + W, H)).filter(ImageFilter.GaussianBlur(r.uniform(26, 46)))
    bg = ImageEnhance.Brightness(bg).enhance(r.uniform(0.46, 0.76))
    bg = ImageEnhance.Color(bg).enhance(r.uniform(1.0, 1.65))
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    cx, cy = W * r.uniform(0.35, 0.65), H * r.uniform(0.35, 0.65)
    dist = np.sqrt(((xx - cx) / (W / 2)) ** 2 + ((yy - cy) / (H / 2)) ** 2)
    mask = np.clip(1.15 - r.uniform(0.42, 0.7) * dist ** 2, r.uniform(0.16, 0.32), 1.0)[..., None]
    frame = Image.fromarray((np.asarray(bg, dtype=np.float32) * mask).clip(0, 255).astype(np.uint8))
    frame.paste(cover.convert("RGB").resize((COVER, COVER), Image.LANCZOS), ((W - COVER) // 2, COVER_Y))
    return frame


def thumbprint(img: Image.Image, s: int = THUMB_GRID) -> str:
    """A 16x16 RGB reduction, hex encoded: the picture as a thumbnail, not as pixels."""
    return np.asarray(img.convert("RGB").resize((s, s), Image.LANCZOS), dtype=np.uint8).tobytes().hex()


def distance(a: str, b: str) -> float:
    x = np.frombuffer(bytes.fromhex(a), dtype=np.uint8).astype(np.float32)
    y = np.frombuffer(bytes.fromhex(b), dtype=np.uint8).astype(np.float32)
    return 255.0 if x.shape != y.shape else float(np.abs(x - y).mean())


def legible(fam, art: Image.Image):
    """Pick a family shim whose title colour will actually read on this art.

    finish() paints the title in the family accent, which was chosen against the family's
    default palette. Grading moves the art off that palette, and orange on yellow clears a
    brightness test while being unreadable — so the accent is kept only when it is far away
    in colour as well, and otherwise the drop borrows the treatment the mono families use.
    """
    band = np.asarray(art.convert("RGB").crop((0, int(art.width * 0.05), art.width,
                                               int(art.width * 0.23))), dtype=np.float32)
    mean = band.reshape(-1, 3).mean(axis=0)
    acc = np.array(hex_rgb(fam.accent), dtype=np.float32)
    lum = lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]          # noqa: E731
    if fam.id not in ("void", "prism", "chrome") \
            and abs(lum(acc) - lum(mean)) >= 55 and float(np.linalg.norm(acc - mean)) >= 120:
        return fam
    return SimpleNamespace(id="prism", accent=fam.accent)


def redraw(fam, drop: dict, artist: str, taken: list[tuple[str, str]]) -> tuple[Image.Image, str, str, float, int]:
    """Draw this drop until it differs from every earlier one on both surfaces."""
    seed = int(drop["seed"]) % 2_147_483_647
    best = None
    for attempt in range(ATTEMPTS):
        roll = (seed + attempt * 7919) % 2_147_483_647
        spread = 1.0 + 3.0 * attempt / max(1, ATTEMPTS - 1)
        art = grade(framing(structure(procedural(fam, roll), fam, roll), roll), roll, spread)
        cover = published(finish(art, drop.get("title") or "", artist, legible(fam, art), roll))
        face, mark = thumbprint(cover), thumbprint(tile(cover, roll))
        gap = min([255.0, *(distance(face, c) for c, _ in taken), *(distance(mark, t) for _, t in taken)])
        if best is None or gap > best[3]:
            best = (cover, face, mark, gap, attempt + 1)
        if gap >= MIN_DISTANCE:
            break
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = ap.parse_args()

    profile = load_profile()
    cat = catalog.load(CATALOG_PATH, profile)
    drops = sorted(cat.get("drops") or [], key=lambda d: d.get("date", ""))
    covers = SITE / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    taken: list[tuple[str, str]] = []

    for drop in drops:
        date = drop.get("date")
        if not date or drop.get("seed") is None:
            log(f"recover-covers: {date or '?'} has no seed, left alone")
            continue
        fam = profile.family(drop.get("family") or profile.families[0].id)
        cover, face, mark, gap, tries = redraw(fam, drop, profile.artist["name"], taken)
        taken.append((face, mark))
        flag = "" if gap >= MIN_DISTANCE else "  << could not clear the bar"
        log(f"recover-covers: {date}  {str(drop.get('title'))[:28]:28} gap={gap:6.2f}  tries={tries:3}{flag}")
        if not args.dry_run:
            cover.resize((600, 600), Image.LANCZOS).save(covers / f"{date}.jpg", quality=85, optimize=True)
            drop["art_coverprint"], drop["art_thumbprint"] = face, mark

    closest = min((min(distance(a[0], b[0]), distance(a[1], b[1]))
                   for a, b in itertools.combinations(taken, 2)), default=255.0)
    log(f"recover-covers: closest pair across both surfaces = {closest:.2f} (bar {MIN_DISTANCE})")
    if not args.dry_run:
        catalog.save(cat, CATALOG_PATH)
        log(f"recover-covers: redrew {len(taken)} covers and stamped the catalogue")
    return 0 if closest >= MIN_DISTANCE else 1


if __name__ == "__main__":
    raise SystemExit(main())
