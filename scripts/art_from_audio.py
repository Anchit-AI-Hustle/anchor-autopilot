"""Redraw every cover from the track it belongs to.

The covers on the site were drawn from a 'visual family' seeded by the drop date. That seed
never saw the title and never saw the audio, so the correlation between a cover and its song
was zero by construction: a 155 BPM bunker track and a mid-tempo mechanical one got the same
red spiral, and five of ten drops came out as one composition in different colours.

This measures the released master first - energy envelope, sub weight, brightness, onset
density, spectral flatness - and draws from that. Composition comes from a library of nine
forms picked by measured character plus the title, so two drops only look alike if they
genuinely sound alike.

  python scripts/art_from_audio.py --dates 2026-09-04,2026-09-05      # some
  python scripts/art_from_audio.py                                    # every drop
  python scripts/art_from_audio.py --dry-run                          # report, write nothing
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
FONTS = ROOT / "assets" / "fonts"
DISPLAY, MONO = FONTS / "Anton.ttf", FONTS / "JetBrainsMono-Bold.ttf"
CATALOG = SITE / "data" / "catalog.json"
S = 1200                       # drawn big, saved at 1000 - cheap antialiasing
OUT = 1000                     # above the 680 the full-length video samples, so it never upscales
SR = 22050
BARS = 200


def fetch(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "anchor-autopilot/1.0"})
    with urllib.request.urlopen(req, timeout=600) as r, dest.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    return dest


def decode(p: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "f32le", "-ac", "1",
                          "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def measure(y: np.ndarray) -> dict:
    """Everything the drawing needs, from the audio itself."""
    # some released masters still carry rendered silence on the end; the picture should show
    # the music, not the bug
    coarse = np.sqrt(np.mean(np.square(y[:len(y) // 1024 * 1024].reshape(-1, 1024)), axis=1))
    live = np.where(coarse > coarse.max() * 0.02)[0]
    if len(live):
        y = y[: (live[-1] + 1) * 1024]

    N, HOP = 2048, 512
    n = 1 + (len(y) - N) // HOP
    fr = np.lib.stride_tricks.as_strided(
        y, shape=(n, N), strides=(y.strides[0] * HOP, y.strides[0])).copy() * np.hanning(N)
    mag = np.abs(np.fft.rfft(fr, axis=1))
    freq = np.fft.rfftfreq(N, 1 / SR)
    pw = mag ** 2
    tot = pw.sum(axis=1) + 1e-12
    flux = np.maximum(0, np.diff(mag, axis=0)).sum(axis=1)
    flux = flux / (flux.max() + 1e-9)
    secs = len(y) / SR

    blocks = y[: len(y) // BARS * BARS].reshape(BARS, -1)
    env = np.sqrt(np.square(blocks).mean(axis=1))
    env = env / (env.max() + 1e-9)
    low, high = [], []
    for b in blocks:
        m = np.abs(np.fft.rfft(b * np.hanning(len(b)))) ** 2
        f = np.fft.rfftfreq(len(b), 1 / SR)
        t = m.sum() + 1e-12
        low.append(float(m[f < 150].sum() / t))
        high.append(float(m[f > 4000].sum() / t))

    return {
        "env": [float(v) for v in env],
        "low": low,
        "high": high,
        "seconds": round(secs, 1),
        "centroid": float(((pw * freq).sum(axis=1) / tot).mean()),
        "sub_pct": round(float((pw[:, freq < 120].sum(axis=1) / tot).mean()) * 100, 1),
        "onsets": int((flux > flux.mean() + flux.std()).sum() / secs * 60),
        "noisiness": round(float((np.exp(np.log(pw + 1e-12).mean(axis=1)) /
                                  (pw.mean(axis=1) + 1e-12)).mean()), 4),
    }


PAL = {
 "oxide":    {"bg":(14,11,10),  "ink":(238,232,226), "hot":(208,84,26),  "cool":(96,44,24),  "dim":(58,44,38)},
 "sodium":   {"bg":(13,12,9),   "ink":(242,238,228), "hot":(233,166,26), "cool":(112,74,12), "dim":(58,52,36)},
 "ember":    {"bg":(15,9,9),    "ink":(240,230,228), "hot":(216,48,20),  "cool":(98,22,12),  "dim":(62,38,36)},
 "steel":    {"bg":(9,11,13),   "ink":(228,236,242), "hot":(126,162,188),"cool":(42,64,82),  "dim":(36,48,58)},
 "acid":     {"bg":(10,12,8),   "ink":(234,242,224), "hot":(170,219,24), "cool":(68,92,14),  "dim":(44,54,32)},
 "concrete": {"bg":(12,12,12),  "ink":(234,230,224), "hot":(190,182,170),"cool":(76,72,68),  "dim":(50,48,46)},
 "bone":     {"bg":(16,14,12),  "ink":(240,234,224), "hot":(214,196,158),"cool":(88,78,64),  "dim":(56,50,42)},
}

# ---------------------------------------------------------------- shared frame
def grain(im, noisiness, seed):
    amt = int(min(34, 100 * noisiness))
    if not amt: return im
    g = (np.random.default_rng(seed).random((S//3, S//3, 1)) * amt).astype(np.uint8)
    gi = Image.fromarray(np.repeat(g, 3, axis=2)).resize((S, S), Image.BILINEAR)
    return Image.blend(im, Image.blend(im, gi, .5), .30)

def scanlines(d, p, onsets):
    pitch = max(6, int(2600 / onsets))
    for x in range(0, S, pitch):
        d.line([(x, 0), (x, S)], fill=(*p["cool"], 20), width=1)

def break_title(title):
    """Break where the phrase breaks, not down the middle - 'THEN DO / IT' was wrong."""
    w = title.upper().split()
    if len(w) <= 2: return [" ".join(w)]
    if len(w) == 3: return [w[0], " ".join(w[1:])] if len(w[0]) >= 4 else [" ".join(w[:2]), w[2]]
    h = len(w)//2
    return [" ".join(w[:h]), " ".join(w[h:])]

def fit(text, room, big, small):
    for size in range(big, small-1, -2):
        f = ImageFont.truetype(str(DISPLAY), size)
        if f.getbbox(text)[2] <= room: return f
    return ImageFont.truetype(str(DISPLAY), small)

def luma(im, box):
    """Mean brightness of the region type is about to sit on."""
    a = np.asarray(im.crop(box).convert("L")).astype(float)
    return float(a.mean())

def frame(im, meta, bottom_type=False):
    p = PAL[meta["palette"]]
    d = ImageDraw.Draw(im, "RGBA")
    light = luma(im, (0, 0, S, S)) > 120            # a light-ground cover (Robot Love)
    ink   = (22, 18, 14) if light else p["ink"]
    shade = (255, 255, 255, 120) if light else (0, 0, 0, 150)
    M, room = int(S*0.068), S - 2*int(S*0.068)
    lines = break_title(meta["title"])
    f = fit(max(lines, key=len), room, int(S*0.19), int(S*0.048))

    # measure the real ink box - Big Shoulders sets well below its nominal size, so a
    # line-height guessed from f.size dropped the last line straight onto the footer
    boxes = [d.textbbox((0, 0), ln, font=f) for ln in lines]
    lead = int(f.size * 0.78)
    block = lead * (len(lines) - 1) + (boxes[-1][3] - boxes[-1][1])
    top_ink = boxes[0][1]

    foot_top = S - M - int(S*0.030) - int(S*0.040)      # footer row, plus air above it
    y = (foot_top - block - top_ink) if bottom_type else (M - top_ink)
    for ln, bx in zip(lines, boxes):
        d.text((M+3, y+3), ln, font=f, fill=shade)
        d.text((M, y), ln, font=f, fill=ink)
        y += lead
    fm = ImageFont.truetype(str(MONO), int(S*0.021))
    yf = S - M - int(S*0.030)
    foot_ink = (8, 6, 4, 255) if light else (*p["ink"], 255)
    d.text((M, yf), "A N C H O R", font=fm, fill=foot_ink)
    # No musical key in the footer. Detected straight from the released masters, the key
    # the catalogue claims disagrees with the audio on three of the four tracks a
    # Krumhansl-Schmuckler profile is confident about, and three more come back ambiguous.
    # An unreliable number burned into permanent artwork is worse than no number.
    tag = f"{meta['bpm']} BPM"
    hot = p["hot"] if not light else (122, 38, 8)      # the bone ground washes out the accent
    d.text((S - M - d.textbbox((0,0), tag, font=fm)[2], yf), tag, font=fm, fill=(*hot, 255))
    return im

def new(meta):
    p = PAL[meta["palette"]]
    im = Image.new("RGB", (S, S), p["bg"])
    return im, ImageDraw.Draw(im, "RGBA"), p

# ---------------------------------------------------------------- compositions
def then_do_it(meta, env):
    """Imperative, rawstyle, energy climbing to a late peak: chevrons stacking upward."""
    im, d, p = new(meta); scanlines(d, p, meta["onsets"])
    for i in range(9):
        t = i/8
        y = S*0.94 - t*S*0.62
        w = S*0.055 + t*S*0.035
        a = int(40 + 190*t)
        col = p["hot"] if i >= 6 else p["cool"]
        d.polygon([(S*0.10, y), (S*0.50, y-S*0.17-t*S*0.05), (S*0.90, y),
                   (S*0.90, y+w), (S*0.50, y-S*0.17-t*S*0.05+w), (S*0.10, y+w)], fill=(*col, a))
    return im

def silent_transmission(meta, env):
    """A broadcast that isn't silent at all - dense signal bands, one channel dropped out."""
    im, d, p = new(meta)
    e = np.array(env["env"])
    rows = 26
    for i in range(rows):
        y = S*0.16 + i*(S*0.72/rows)
        v = e[int(i/rows*len(e))]
        segs = int(4 + v*22)
        gap = S*0.86/segs
        for s in range(segs):
            if i == 17 and 3 < s < segs-3: continue        # the dropout
            x = S*0.07 + s*gap
            d.rectangle([x, y, x + gap*0.62, y + S*0.012],
                        fill=(*(p["hot"] if v > .72 else p["cool"]), int(70+150*v)))
    d.rectangle([S*0.07, S*0.16+17*(S*0.72/rows)-4, S*0.93, S*0.16+17*(S*0.72/rows)+S*0.012+4],
                outline=(*p["hot"], 150), width=2)
    return im

def stay_with_me(meta, env):
    """155 BPM, majorkey, the most compressed track here: a colonnade that never lets up."""
    im, d, p = new(meta)
    e = np.array(env["env"]); n = 40
    top, floor = S*0.10, S*0.70
    for i in range(n):
        v = float(e[int(i/n*len(e))])
        x = i*(S/n)
        h = (floor - top) * (0.34 + 0.66*v)
        d.rectangle([x, floor-h, x + (S/n)*0.70, floor],
                    fill=(*(p["hot"] if v > .78 else p["cool"]), int(130 + 110*v)))
    d.rectangle([0, floor, S, floor+4], fill=(*p["ink"], 180))
    return im

def robot_love(meta, env):
    """Two mechanisms turning against each other, never quite meshing.

    The one light cover in the set - printed ink on bone board rather than glow on black, so
    the channel grid has tonal range instead of nine dark tiles."""
    p = PAL[meta["palette"]]
    im = Image.new("RGB", (S, S), (222, 214, 200))
    d = ImageDraw.Draw(im, "RGBA")
    for y in range(0, S, 9):
        d.line([(0, y), (S, y)], fill=(120, 110, 96, 30), width=1)
    ink, acc = (26, 22, 18), (176, 66, 20)
    for cx, cy, col in ((S*0.36, S*0.44, acc), (S*0.66, S*0.56, ink)):
        for k in range(7):
            r = S*(0.055 + k*0.038)
            d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=(*col, 235-k*18), width=max(3, 10-k))
        for t in range(12):                                  # teeth
            a = t/12*2*math.pi
            r0, r1 = S*0.255, S*0.290
            d.line([(cx+r0*math.cos(a), cy+r0*math.sin(a)), (cx+r1*math.cos(a), cy+r1*math.sin(a))],
                   fill=(*col, 230), width=9)
    return im

def where_it_begins(meta, env):
    """The longest, darkest, cleanest track: a horizon, almost nothing above it."""
    im, d, p = new(meta)
    hz = S*0.70
    for i in range(90):                                       # sky glow above the horizon
        y = hz - i*(S*0.42/90)
        d.rectangle([0, y, S, y+3], fill=(*p["cool"], int(74 - i*0.78)))
    for i in range(60):                                       # ground haze
        y = hz + i*(S*0.30/60)
        d.rectangle([0, y, S, y+2], fill=(*p["cool"], int(14 + i*3.0)))
    d.rectangle([0, hz, S, hz+3], fill=(*p["hot"], 210))
    ap = S*0.048                                              # one small aperture of light
    d.rectangle([S*0.5-ap/2, hz-S*0.30, S*0.5+ap/2, hz], fill=(*p["hot"], 120))
    d.rectangle([S*0.5-ap/2, hz-S*0.30, S*0.5+ap/2, hz-S*0.29], fill=(*p["ink"], 200))
    return im

def signal_detected(meta, env):
    """Shortest track, one event, then it falls off a cliff: a reticle locking on a spike."""
    im, d, p = new(meta)
    cx, cy = S*0.5, S*0.56
    for k in range(52):                                       # sweep of the field, amber
        r = S*0.54 - k*S*0.0094
        d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(*p["cool"], 16))
    for r in (S*0.30, S*0.21, S*0.12):
        d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=(*p["hot"], 190), width=4)
    for a0 in (0, 90, 180, 270):                              # reticle ticks
        a = math.radians(a0)
        d.line([(cx+S*0.30*math.cos(a), cy+S*0.30*math.sin(a)),
                (cx+S*0.40*math.cos(a), cy+S*0.40*math.sin(a))], fill=(*p["cool"], 170), width=4)
    for k in range(5):                                        # the return, decaying
        rr = S*(0.055 + k*0.052)
        d.arc([cx-rr, cy-rr, cx+rr, cy+rr], 200, 340, fill=(*p["hot"], 200-k*34), width=max(3, 11-k*2))
    d.rectangle([cx-S*0.016, cy-S*0.34, cx+S*0.016, cy+S*0.02], fill=(*p["hot"], 250))
    d.ellipse([cx-S*0.040, cy-S*0.040, cx+S*0.040, cy+S*0.040], fill=(*p["hot"], 255))
    d.ellipse([cx-S*0.016, cy-S*0.016, cx+S*0.016, cy+S*0.016], fill=(*p["bg"], 255))
    return im

def grid_blade(meta, env):
    """Heaviest low end and the dirtiest master: a grid, cut."""
    im, d, p = new(meta)
    step = S/13
    for i in range(14):
        d.line([(i*step, 0), (i*step, S)], fill=(*p["cool"], 120), width=3)
        d.line([(0, i*step), (S, i*step)], fill=(*p["cool"], 120), width=3)
    blade = [(S*-0.05, S*0.72), (S*1.05, S*0.20), (S*1.05, S*0.30), (S*-0.05, S*0.82)]
    d.polygon(blade, fill=(*p["hot"], 245))
    d.polygon([(S*-0.05, S*0.845), (S*1.05, S*0.325), (S*1.05, S*0.345), (S*-0.05, S*0.865)],
              fill=(*p["hot"], 110))
    return im

def project_mayhem(meta, env):
    """Fastest, brightest, thinnest low end, most chaotic: the plate has shattered."""
    im, d, p = new(meta)
    rng = np.random.default_rng(meta["seed"])
    cx, cy = S*0.52, S*0.55
    pts = [(cx + S*0.62*math.cos(a), cy + S*0.62*math.sin(a))
           for a in np.sort(rng.random(11) * 2*math.pi)]
    for i in range(len(pts)):
        a, b = pts[i], pts[(i+1) % len(pts)]
        off = (rng.random(2) - .5) * S*0.09
        tri = [(cx+off[0], cy+off[1]), (a[0]+off[0], a[1]+off[1]), (b[0]+off[0], b[1]+off[1])]
        shade = p["hot"] if i % 3 == 0 else (p["cool"] if i % 3 == 1 else p["dim"])
        d.polygon(tri, fill=(*shade, 215), outline=(*p["bg"], 255))
    return im

def crossing_the_threshold(meta, env):
    """Busiest track on the list: a doorway, light forcing through a heavy wall."""
    im, d, p = new(meta)
    for i in range(30):                                        # the wall
        y = i*(S/30)
        d.rectangle([0, y, S, y + S/30*0.86], fill=(*p["dim"], 80 + (i % 3)*22))
    gw = S*0.19
    d.rectangle([S*0.5-gw/2, S*0.10, S*0.5+gw/2, S*0.90], fill=(*p["bg"], 255))
    for k in range(9):                                         # the light in the gap
        t = k/8
        d.rectangle([S*0.5-gw/2 + t*gw*0.5, S*0.10 + t*S*0.06,
                     S*0.5+gw/2 - t*gw*0.5, S*0.90 - t*S*0.06],
                    fill=(*p["hot"], int(26 + 26*k)))
    d.rectangle([S*0.5-gw/2-4, S*0.10, S*0.5-gw/2, S*0.90], fill=(*p["ink"], 190))
    d.rectangle([S*0.5+gw/2, S*0.10, S*0.5+gw/2+4, S*0.90], fill=(*p["ink"], 190))
    return im


# ---------------------------------------------------------------- selection
FORMS = {
    "chevrons":  (then_do_it,             "oxide"),
    "broadcast": (silent_transmission,    "steel"),
    "colonnade": (stay_with_me,           "ember"),
    "mechanism": (robot_love,             "bone"),
    "horizon":   (where_it_begins,        "steel"),
    "reticle":   (signal_detected,        "sodium"),
    "grid":      (grid_blade,             "acid"),
    "shatter":   (project_mayhem,         "ember"),
    "doorway":   (crossing_the_threshold, "concrete"),
}

# a title word is the strongest hint about what a cover should show, so it wins when present
WORDS = {
    "grid": "grid", "blade": "grid", "circuit": "grid", "sector": "grid", "axis": "grid",
    "signal": "reticle", "ping": "reticle", "detect": "reticle", "relay": "reticle",
    "carrier": "broadcast", "transmis": "broadcast", "frequency": "broadcast", "static": "broadcast",
    "servo": "mechanism", "robot": "mechanism", "machine": "mechanism", "engine": "mechanism",
    "threshold": "doorway", "door": "doorway", "gate": "doorway", "breach": "doorway",
    "begin": "horizon", "origin": "horizon", "deep": "horizon", "descent": "horizon",
    "flashover": "shatter", "mayhem": "shatter", "shatter": "shatter", "fracture": "shatter",
    "lockstep": "colonnade", "stay": "colonnade", "pressure": "colonnade", "tension": "colonnade",
}


def choose(title: str, m: dict) -> str:
    """Title first, then the measurements - always deterministic, never random."""
    low = title.lower()
    for word, form in WORDS.items():
        if word in low:
            return form
    if m["sub_pct"] > 70:              return "grid"        # heaviest low end
    if m["centroid"] < 460:            return "horizon"     # darkest
    if m["centroid"] > 900:            return "shatter"     # brightest, thinnest
    if m["noisiness"] > 0.055:         return "reticle"
    if m["onsets"] > 370:              return "colonnade"
    if m["seconds"] > 300:             return "horizon"
    return "chevrons"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dates", default="", help="comma separated; default every drop")
    ap.add_argument("--work", default="build-art")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    want = [d.strip() for d in args.dates.split(",") if d.strip()]
    drops = [d for d in cat["drops"] if not want or d["date"] in want]
    drops.sort(key=lambda d: d["date"])
    if not drops:
        print("no drops matched", file=sys.stderr)
        return 1

    work = Path(args.work)
    for drop in drops:
        date, title = drop["date"], drop["title"]
        audio = fetch(drop["audio_url"], work / Path(drop["audio_url"]).name)
        m = measure(decode(audio))
        form = choose(title, m)
        fn, palette = FORMS[form]
        meta = dict(palette=palette, title=title, bpm=drop["bpm"], key=drop["key"],
                    onsets=m["onsets"], noisiness=m["noisiness"], seed=int(date.replace("-", "")))
        print(f"{date}  {title[:24]:24} {form:10} {palette:9} "
              f"sub {m['sub_pct']:4.1f}%  centroid {m['centroid']:5.0f}Hz  "
              f"onsets {m['onsets']:4}  flat {m['noisiness']:.3f}")
        if args.dry_run:
            continue
        im = fn(meta, m)
        im = grain(im, m["noisiness"], meta["seed"])
        im = frame(im, meta, bottom_type=form in ("horizon", "doorway", "colonnade"))
        dest = SITE / "covers" / f"{date}.jpg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.resize((OUT, OUT), Image.LANCZOS).save(dest, quality=92, subsampling=0, optimize=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
