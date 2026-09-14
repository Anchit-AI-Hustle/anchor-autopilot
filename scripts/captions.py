"""Write a caption track for each drop, describing the music rather than mishearing it.

YouTube runs speech recognition over every upload. Most of this catalogue is instrumental or
carries only a short vocal hook, so it produces nothing usable - which is why the captions on
the channel read as broken or missing. Shipping a real track fixes it two ways: it is what a
deaf or hard-of-hearing viewer actually needs, and any manual track stops YouTube showing its
auto-generated guess.

Sections are measured, not assumed. A techno breakdown is not "quieter" - it is the kick
leaving - so sections are classified on the weight of the low end, with level only as a
tiebreak. Classifying on loudness called a -2.4 dB section with 75% of its energy under 150 Hz
a "breakdown", which is plainly wrong and would mislead the viewer the captions exist for.

Buffer cannot carry these: its YoutubePostMetadata has no captions field, so the .srt is
uploaded by hand in Studio (Subtitles -> upload file). Same for Instagram.

  python scripts/captions.py                      # every drop -> build-captions/
  python scripts/captions.py --dates 2026-09-13
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "site" / "data" / "catalog.json"
SR = 22050


def fetch(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "anchor-autopilot/1.0"})
    with urllib.request.urlopen(req, timeout=600) as r, dest.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    return dest


def decode(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le",
                          "-ac", "1", "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def sections(y, hop=0.5):
    """Split into musical sections and name each by its level and low-end weight."""
    n = int(SR * hop)
    blocks = y[:len(y) // n * n].reshape(-1, n)
    rms = np.sqrt((blocks ** 2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(rms / rms.max())

    low = []
    for b in blocks:
        m = np.abs(np.fft.rfft(b * np.hanning(len(b)))) ** 2
        f = np.fft.rfftfreq(len(b), 1 / SR)
        low.append(float(m[f < 150].sum() / (m.sum() + 1e-12)))
    low = np.array(low)

    k = 9                                            # ~4.5s smoothing: musical, not per-beat
    sm = np.convolve(db, np.ones(k) / k, mode="same")
    lowsm = np.convolve(low, np.ones(k) / k, mode="same")

    # A techno breakdown is not "quieter" - it is the kick LEAVING. A percentile on loudness
    # called a -2.4 dB section with 75% of its energy under 150 Hz a "breakdown", which is
    # plainly wrong and would mislead the viewer the captions exist for. Classify on the
    # low end, which is what the genre actually does, and on level only as a tiebreak.
    KICK = 0.45                                      # share of energy under 150 Hz
    state = np.where(lowsm >= KICK, 1, 0)            # 1 = kick present, 0 = stripped

    bounds, start = [], 0
    for i in range(1, len(state)):
        if state[i] != state[i - 1]:
            if (i - start) * hop >= 8:               # shorter than 8s is a fill, not a section
                bounds.append((start, i))
                start = i
    bounds.append((start, len(state)))

    raw, prev_kick = [], None
    for a, b in bounds:
        t0, t1 = a * hop, b * hop
        seg_db, seg_low = float(sm[a:b].mean()), float(lowsm[a:b].mean())
        kick = seg_low >= KICK
        rising = (sm[a:b][-1] - sm[a:b][0]) > 2 if b - a > 2 else False
        if not raw:
            label = "full kick from the top" if kick else "filtered intro"
        elif kick and prev_kick is False:
            label = "the drop — kick and bass return"
        elif kick and rising:
            label = "building"
        elif kick:
            label = "driving — heavy low end" if seg_low > 0.70 else "driving"
        elif rising:
            label = "kick drops out — tension building"
        else:
            label = "breakdown — kick stripped out"
        raw.append([t0, t1, label, seg_db, seg_low])
        prev_kick = kick

    # never print the same caption twice in a row - merge instead
    out = []
    for seg in raw:
        if out and out[-1][2] == seg[2]:
            out[-1][1] = seg[1]
        else:
            out.append(seg)
    if out:
        out[-1][2] = "outro — resolving out"
        if len(out) > 1 and out[-2][2] == "outro — resolving out":
            out[-2][1] = out[-1][1]; out.pop()
    return [tuple(o) for o in out]


def ts(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


def srt(secs, genre, bpm):
    """A caption track a deaf viewer can actually use: what is playing, and when it changes."""
    lines = []
    for i, (t0, t1, label, _, _) in enumerate(secs, 1):
        text = f"[{genre.lower()}, {bpm} BPM — {label}]" if i == 1 else f"[{label}]"
        lines += [str(i), f"{ts(t0)} --> {ts(t1)}", text, ""]
    return "\n".join(lines)


def slug(title: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in title).strip("-")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dates", default="", help="comma separated; default every drop")
    ap.add_argument("--out", default="build-captions")
    ap.add_argument("--work", default="build-captions/work")
    args = ap.parse_args(argv)

    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    want = [d.strip() for d in args.dates.split(",") if d.strip()]
    drops = sorted((d for d in cat["drops"] if not want or d["date"] in want),
                   key=lambda d: d["date"])
    if not drops:
        print("no drops matched", file=sys.stderr)
        return 1

    out, work = Path(args.out), Path(args.work)
    out.mkdir(parents=True, exist_ok=True)
    for i, drop in enumerate(drops, 1):
        audio = fetch(drop["audio_url"], work / Path(drop["audio_url"]).name)
        secs = sections(decode(audio))
        genre = (drop.get("genre_line") or "techno").split(",")[0].strip()
        text = srt(secs, genre, drop["bpm"])
        dest = out / f"{i:02d}-{slug(drop['title'])}.srt"
        dest.write_text(text, encoding="utf-8")
        print(f"{drop['date']}  {drop['title'][:26]:26} {len(secs):2} sections  -> {dest.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
