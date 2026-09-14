"""Re-publish every drop from the cover that is actually on the site.

Why this exists
---------------
The ten covers on the site were redrawn (scripts/recover_covers.py) because five rust drops
had come out as five near-identical orange tiles. The Shorts already on YouTube were rendered
from the OLD art, so the channel and the site now disagree about what every song looks like -
and a Short cannot be re-skinned in place: the cover is burned into all 45 seconds of frames,
and a published video's file cannot be replaced.

So each drop is re-rendered from site/covers/<date>.jpg - the exact file the website serves -
and posted again. The old video is retired by hand afterwards.

It also builds a 16:9 full-length video per song, because until now the channel only ever had
the 45s cut and every description promised "full song out soon".

Audio is pulled from the drop's own GitHub release, so this needs nothing that is not already
public. Nothing here generates music.

    python scripts/republish.py --dates 2026-09-04,2026-09-05 --out build-republish
    python scripts/republish.py --stamp build-republish        # after publishing
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from anchor import catalog, video as V                            # noqa: E402
from anchor.config import CATALOG_PATH, SITE, load_profile        # noqa: E402
from anchor.util import log                                       # noqa: E402

FONTS = ROOT / "assets" / "fonts"
FW, FH, FPS = 1920, 1080, 30          # full-length video: 16:9, so YouTube never reads it as a Short
FCOVER, FCX, FCY = 680, 200, 200      # cover square, left column
TX = 990                              # text column
SITE_URL = "anchor.anchit-tandon.com"


# --------------------------------------------------------------------------- helpers
def fetch(url: str, dest: Path) -> Path:
    """Pull a release asset. The repo is public, so no token is needed."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "anchor-republish/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f)
    if dest.stat().st_size < 10_000:
        raise RuntimeError(f"{url} came back as {dest.stat().st_size} bytes")
    return dest


def cover_at(date: str, size: int, dest: Path) -> Path:
    """The published cover, at whatever size the renderer wants."""
    Image.open(SITE / "covers" / f"{date}.jpg").convert("RGB") \
        .resize((size, size), Image.LANCZOS).save(dest, quality=95)
    return dest


def describe(drop: dict, kind: str) -> str:
    """A release note, not a spec sheet: what it sounds like first, the plumbing last."""
    lead = ("The full track, start to finish." if kind == "full"
            else "Full song out soon — this is the 45s cut.")
    tags = "#hardtechno #industrialtechno #techno" + ("" if kind == "full" else " #shorts")
    return "\n".join([
        lead,
        f"{drop['title']} · {drop['genre_line']} · {drop['bpm']} BPM",
        "",
        f"{drop['style_line']}.",
        "",
        f"Stream or download the full track, free: {SITE_URL}",
        "A new ANCHOR track every day.",
        "Made with AI-assisted music tools.",
        "",
        tags,
    ])


# --------------------------------------------------------------------------- renders
def cut(audio: Path, seconds: int, dest: Path) -> Path:
    """The Short's slice of the track, faded so it does not stop mid-bar."""
    fade = max(0, seconds - 2)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(audio), "-t", str(seconds),
                    "-af", f"afade=t=out:st={fade}:d=2", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", str(dest)], check=True, timeout=600)
    return dest


def short_backdrop(cover: Path, seed: int, dest: Path) -> Path:
    """The blurred plate behind the cover, seeded.

    anchor/video.py gives every Short the same fixed treatment here. That plate is two
    thirds of a 9:16 frame, so a fixed treatment makes two drops of one family read alike
    however far apart their covers are. Seeding crop, blur, weight and vignette off the
    drop's own seed keeps the surround as distinct as the art it is made from.
    """
    r = random.Random(seed ^ 0x9E3779B9)
    img = Image.open(cover).convert("RGB").resize((V.H, V.H), Image.LANCZOS)
    left = int((V.H - V.W) * r.uniform(0.1, 0.9))
    img = img.crop((left, 0, left + V.W, V.H)).filter(ImageFilter.GaussianBlur(r.uniform(26, 46)))
    img = ImageEnhance.Color(ImageEnhance.Brightness(img).enhance(r.uniform(0.46, 0.76))) \
        .enhance(r.uniform(1.0, 1.65))
    yy, xx = np.mgrid[0:V.H, 0:V.W].astype(np.float32)
    cx, cy = V.W * r.uniform(0.35, 0.65), V.H * r.uniform(0.35, 0.65)
    d = np.sqrt(((xx - cx) / (V.W / 2)) ** 2 + ((yy - cy) / (V.H / 2)) ** 2)
    mask = np.clip(1.15 - r.uniform(0.42, 0.7) * d ** 2, r.uniform(0.16, 0.32), 1.0)[..., None]
    Image.fromarray((np.asarray(img, dtype=np.float32) * mask).clip(0, 255).astype(np.uint8)) \
        .save(dest, quality=92)
    return dest


def short(drop: dict, profile, audio: Path, work: Path, out: Path) -> dict:
    """The 45s cut. Mirrors anchor.video.render_short but supplies its own seeded backdrop,
    so this runs against the tree as it stands rather than needing a change in anchor/."""
    fam = profile.family(drop["family"])
    seconds = int(drop.get("short_s") or 45)
    clip = cut(audio, seconds, work / "cut.m4a")
    duration = V.media_summary(clip)["duration"]
    texts = {
        "artist": "  ".join(profile.artist["name"].upper()),
        "title": drop["title"].upper(),
        "meta": f"{drop['lane_name'].upper()}  ·  {drop['bpm']} BPM",   # no musical key
        "footer": f"{profile.artist['handle']}  ·  NEW TRACK EVERY DAY",
    }
    tp = {}
    for k, v in texts.items():
        f = work / f"text_{k}.txt"
        f.write_text(v, encoding="utf-8")
        tp[k] = f
    cover = cover_at(drop["date"], 1080, work / "cover_1080.jpg")
    graph = V.build_graph(fam, int(drop["bpm"]), duration, tp)
    V.run(["ffmpeg", "-y", "-hide_banner", "-v", "error",
           "-loop", "1", "-framerate", str(V.FPS),
           "-i", str(short_backdrop(cover, int(drop["seed"]), work / "background.jpg")),
           "-loop", "1", "-framerate", str(V.FPS), "-i", str(cover),
           "-i", str(clip),
           "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
           "-t", f"{duration:.3f}", "-r", str(V.FPS),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-maxrate", "8M", "-bufsize", "16M",
           "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-movflags", "+faststart", str(out)], timeout=1800)
    info = V.media_summary(out)
    if (info.get("width"), info.get("height")) != (V.W, V.H):
        raise RuntimeError(f"Short came out {info.get('width')}x{info.get('height')}")
    if abs(info["duration"] - duration) > 0.5:
        raise RuntimeError(f"Short is {info['duration']:.1f}s against {duration:.1f}s of audio")
    return info


def playable(audio: Path, work: Path) -> Path:
    """Trim rendered padding off a track before posting it as the full song.

    Some released files predate eb49ace: the model wrote N seconds whether or not it had
    N seconds of music, so the file ends in digital silence after an abrupt cut. Grid Blade
    is 149.2s of file for 140.2s of music. Posting that as "the full track, start to
    finish" means nine seconds of nothing and a dead stop, so the padding goes and the
    ending gets the taper it never had. A track that already lands cleanly is left alone.
    """
    from anchor import audio as A                                   # noqa: PLC0415
    data = A.decode(audio)
    total, end = len(data) / A.SR, A.music_end(data)
    if total - end < 0.75:
        return audio
    dest = work / f"{audio.stem}-trimmed.m4a"
    fade = max(0.0, end - 4.0)
    V.run(["ffmpeg", "-y", "-v", "error", "-i", str(audio), "-t", f"{end:.3f}",
           "-af", f"afade=t=out:st={fade:.3f}:d={end - fade:.3f}",
           "-c:a", "aac", "-b:a", "256k", "-ar", "48000", str(dest)], timeout=900)
    log(f"republish: {audio.name} carried {total - end:.1f}s of padding - "
        f"trimmed to {end:.1f}s and faded the ending")
    return dest


def full_backdrop(date: str, dest: Path) -> Path:
    """The cover blown up, blurred and vignetted to fill a 16:9 frame."""
    src = Image.open(SITE / "covers" / f"{date}.jpg").convert("RGB")
    scale = max(FW / src.width, FH / src.height) * 1.15
    bg = src.resize((int(src.width * scale), int(src.height * scale)), Image.LANCZOS)
    left, top = (bg.width - FW) // 2, (bg.height - FH) // 2
    bg = bg.crop((left, top, left + FW, top + FH)).filter(ImageFilter.GaussianBlur(38))
    bg = ImageEnhance.Color(ImageEnhance.Brightness(bg).enhance(0.42)).enhance(1.25)
    yy, xx = np.mgrid[0:FH, 0:FW].astype(np.float32)
    dist = np.sqrt(((xx - FW / 2) / (FW / 2)) ** 2 + ((yy - FH / 2) / (FH / 2)) ** 2)
    mask = np.clip(1.12 - 0.5 * dist ** 2, 0.22, 1.0)[..., None]
    Image.fromarray((np.asarray(bg, dtype=np.float32) * mask).clip(0, 255).astype(np.uint8)) \
        .save(dest, quality=92)
    return dest


def full(drop: dict, profile, audio: Path, work: Path, out: Path) -> dict:
    fam = profile.family(drop["family"])
    audio = playable(audio, work)
    duration = V.media_summary(audio)["duration"]
    texts = {
        "artist": "  ".join(profile.artist["name"].upper()),
        "title": drop["title"].upper(),
        "meta": f"{drop['lane_name'].upper()}  ·  {drop['bpm']} BPM",
        "footer": f"{profile.artist['handle']}  ·  NEW TRACK EVERY DAY  ·  FULL TRACK",
    }
    tp = {}
    for k, v in texts.items():
        p = work / f"ftext_{k}.txt"
        p.write_text(v, encoding="utf-8")
        tp[k] = p
    anton, mono = FONTS / "Anton.ttf", FONTS / "JetBrainsMono-Bold.ttf"
    acc = V._ff(fam.accent)
    # showwaves wants #rrggbb; handed the 0x form it silently falls back to a default
    # green that has nothing to do with the art, which is how the first cut came out.
    wave = fam.accent if fam.accent.startswith("#") else "#" + fam.accent
    bar = FW - 400
    graph = ";".join([
        "[0:v]format=yuv420p[bg]",
        "[1:v]format=rgba,setsar=1[cov]",
        "[2:a]asplit=2[aout][aviz]",
        f"[aviz]showwaves=s=820x200:mode=cline:rate={FPS}:scale=sqrt:draw=full:"
        f"colors={wave},format=rgba,colorkey=0x000000:0.30:0.10[viz]",
        f"[bg][cov]overlay=x={FCX}:y={FCY}[s1]",
        f"[s1][viz]overlay=x={TX}:y=600:shortest=1[s2]",
        f"color=c={acc}:s={bar}x6:r={FPS}[barfill]",
        f"color=c=0x2a2a2a:s={bar}x6:r={FPS}[bartrack]",
        f"[bartrack][barfill]overlay=x='-{bar}+{bar}*t/{duration:.3f}':y=0:shortest=1[prog]",
        "[s2][prog]overlay=x=200:y=960:shortest=1[s3]",
        "[s3]"
        f"drawtext=fontfile='{mono}':textfile='{tp['artist']}':fontsize=40:fontcolor=0xF2F2F2:x={TX}:y=250,"
        f"drawtext=fontfile='{anton}':textfile='{tp['title']}':fontsize=104:fontcolor={acc}:"
        f"shadowcolor=0x000000@0.7:shadowx=4:shadowy=6:x={TX}:y=330,"
        f"drawtext=fontfile='{mono}':textfile='{tp['meta']}':fontsize=34:fontcolor=0xE6E6E6:x={TX}:y=480,"
        f"drawtext=fontfile='{mono}':textfile='{tp['footer']}':fontsize=26:fontcolor=0xBDBDBD:"
        "x=(w-text_w)/2:y=1005[vout]",
    ])
    V.run(["ffmpeg", "-y", "-hide_banner", "-v", "error",
           "-loop", "1", "-framerate", str(FPS), "-i", str(full_backdrop(drop["date"], work / "full_bg.jpg")),
           "-loop", "1", "-framerate", str(FPS), "-i", str(cover_at(drop["date"], FCOVER, work / "cover_full.jpg")),
           "-i", str(audio),
           "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
           "-t", f"{duration:.3f}", "-r", str(FPS),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-maxrate", "8M", "-bufsize", "16M",
           "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
           "-movflags", "+faststart", str(out)], timeout=3600)
    info = V.media_summary(out)
    if (info.get("width"), info.get("height")) != (FW, FH):
        raise RuntimeError(f"full video came out {info.get('width')}x{info.get('height')}")
    if abs(info["duration"] - duration) > 1.0:
        raise RuntimeError(f"full video is {info['duration']:.1f}s against {duration:.1f}s of audio")
    return info


# --------------------------------------------------------------------------- drive
def one(date: str, drop: dict, profile, outdir: Path, kinds: list[str]) -> list[dict]:
    work = outdir / "work" / date
    work.mkdir(parents=True, exist_ok=True)
    base = Path(drop["audio_url"]).name
    audio = fetch(drop["audio_url"], work / base)
    made = []
    for kind in kinds:
        d = outdir / f"{date}-{kind}"
        d.mkdir(parents=True, exist_ok=True)
        name = base.replace(".mp3", f"-{kind}.mp4")
        out = d / name
        info = (short if kind == "short" else full)(drop, profile, audio, work, out)
        title = drop["title"] if kind == "short" else f"{drop['title']} (Full Track)"
        # exactly the shape anchor.pipeline.publish reads
        (d / "meta.json").write_text(json.dumps({
            "brief": {**drop, "youtube_title": title[:100],
                      "description": describe(drop, kind), "post_at": drop["post_at"]},
            "video": {"size_bytes": out.stat().st_size},
            "files": {"video": name}, "kind": kind,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"republish: {date} {kind:5} {name}  {info['width']}x{info['height']}  "
            f"{info['duration']:.0f}s  {out.stat().st_size/1e6:.0f}MB")
        made.append({"date": date, "kind": kind, "dir": str(d), "file": name})
    return made


def stamp(outdir: Path) -> int:
    """Write the new YouTube links back into the catalogue after publishing."""
    profile = load_profile()
    cat = catalog.load(CATALOG_PATH, profile)
    drops = {d["date"]: d for d in cat.get("drops") or []}
    n = 0
    for pub_file in sorted(outdir.glob("*/publish.json")):
        meta = json.loads((pub_file.parent / "meta.json").read_text())
        pub = json.loads(pub_file.read_text())
        date, kind = meta["brief"]["date"], meta["kind"]
        link = pub.get("external_link")
        if date not in drops or not link:
            log(f"republish: {date} {kind} has no link yet ({pub.get('status')})")
            continue
        if kind == "short":
            drops[date]["youtube_url"] = link
            drops[date]["buffer_post_id"] = pub.get("post_id")
        else:
            drops[date]["youtube_full_url"] = link
            drops[date]["buffer_full_post_id"] = pub.get("post_id")
        drops[date]["status"] = "sent"
        n += 1
        log(f"republish: {date} {kind} -> {link}")
    if n:
        catalog.save(cat, CATALOG_PATH)
    log(f"republish: stamped {n} links")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", help="comma separated, e.g. 2026-09-04,2026-09-05")
    ap.add_argument("--out", default="build-republish")
    ap.add_argument("--kinds", default="short,full", help="short, full, or both")
    ap.add_argument("--stamp", metavar="DIR", help="write published links back to the catalogue")
    args = ap.parse_args()

    outdir = Path(args.stamp or args.out)
    if args.stamp:
        return stamp(outdir)
    if not args.dates:
        ap.error("--dates is required unless --stamp is given")

    profile = load_profile()
    cat = catalog.load(CATALOG_PATH, profile)
    drops = {d["date"]: d for d in cat.get("drops") or []}
    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    outdir.mkdir(parents=True, exist_ok=True)

    made, missing = [], []
    for date in (d.strip() for d in args.dates.split(",") if d.strip()):
        drop = drops.get(date)
        if not drop or not drop.get("audio_url") or not (SITE / "covers" / f"{date}.jpg").exists():
            missing.append(date)
            log(f"republish: {date} has no drop, no audio or no cover - skipped")
            continue
        made.extend(one(date, drop, profile, outdir, kinds))

    (outdir / "made.json").write_text(json.dumps(made, indent=2), encoding="utf-8")
    log(f"republish: built {len(made)} videos"
        + (f", skipped {len(missing)}: {', '.join(missing)}" if missing else ""))
    return 1 if not made else 0


if __name__ == "__main__":
    raise SystemExit(main())
