"""The full track as a 9:16 video, for Instagram Reels.

The 16:9 full-length videos are for a desktop timeline and YouTube; on a phone they sit in a
letterbox about a third of the screen tall. This renders the same track portrait, using the
Short's own layout and the cover the site now serves.

It exists because Instagram is the one place the full tracks can go out FREE and AUTOMATICALLY:
Buffer publishes Reels directly, and a Reel may run to 15 minutes - every ANCHOR track fits.
YouTube long-form has no free automated route at all.

Buffer's stated Reel requirements, and where each is met:
  5 s - 15 min          every track is 1:41 - 5:58
  aspect 4:5 to 9:16    rendered at 1080x1920, checked after every render
  <= 300 MB             checked after every render
  video <= 25 Mbps      capped at 8 Mbps
  audio <= 128 kbps     requested at 120k: ffmpeg's aac encoder overshoots, and -b:a 128k
                        measured 132.5 kbps on a real track. 120k lands at 123.9.
                        (the 16:9 cut runs 256k and would be rejected outright)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anchor import video as V                                      # noqa: E402
from anchor.config import CATALOG_PATH, load_profile               # noqa: E402
from anchor.util import ffprobe, log                               # noqa: E402

# reuse republish.py's helpers rather than copying them - one definition of the backdrop,
# the cover fetch and the silence trim, so the two renderers can never drift apart
_spec = importlib.util.spec_from_file_location("_republish", Path(__file__).parent / "republish.py")
RP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RP)

MAX_BYTES = 300 * 1024 * 1024
AUDIO_KBPS = 120        # asks for 120, measures ~124 - see the note above


def vertical(drop: dict, profile, audio: Path, work: Path, out: Path) -> dict:
    fam = profile.family(drop["family"])
    audio = RP.playable(audio, work)                 # no rendered silence on the end
    duration = V.media_summary(audio)["duration"]
    texts = {
        "artist": "  ".join(profile.artist["name"].upper()),
        "title": drop["title"].upper(),
        "meta": f"{drop['lane_name'].upper()}  ·  {drop['bpm']} BPM",
        "footer": f"{profile.artist['handle']}  ·  FULL TRACK",
    }
    tp = {}
    for k, v in texts.items():
        f = work / f"vtext_{k}.txt"
        f.write_text(v, encoding="utf-8")
        tp[k] = f

    cover = RP.cover_at(drop["date"], 1080, work / "cover_1080.jpg")
    graph = V.build_graph(fam, int(drop["bpm"]), duration, tp)
    V.run(["ffmpeg", "-y", "-hide_banner", "-v", "error",
           "-loop", "1", "-framerate", str(V.FPS),
           "-i", str(RP.short_backdrop(cover, int(drop["seed"]), work / "vbackground.jpg")),
           "-loop", "1", "-framerate", str(V.FPS), "-i", str(cover),
           "-i", str(audio),
           "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
           "-t", f"{duration:.3f}", "-r", str(V.FPS),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", "6M", "-bufsize", "12M",
           "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-ar", "48000",
           "-movflags", "+faststart", str(out)], timeout=3600)

    info = V.media_summary(out)
    size = out.stat().st_size
    # every one of Buffer's stated limits, checked on the actual file rather than assumed
    if (info.get("width"), info.get("height")) != (V.W, V.H):
        raise RuntimeError(f"{out.name} came out {info.get('width')}x{info.get('height')}, not {V.W}x{V.H}")
    if abs(info["duration"] - duration) > 1.0:
        raise RuntimeError(f"{out.name} is {info['duration']:.1f}s against {duration:.1f}s of audio")
    if not 5 <= info["duration"] <= 15 * 60:
        raise RuntimeError(f"{out.name} is {info['duration']:.1f}s - outside the 5s-15min Reel window")
    if size > MAX_BYTES:
        raise RuntimeError(f"{out.name} is {size/1e6:.0f} MB, over the 300 MB Reel limit")
    # the encoder overshoots what it is asked for, so check the file, not the request.
    # media_summary() reports codec and sample rate but not bitrate, so probe for it.
    probe = ffprobe(out)
    kbps = next((int(st.get("bit_rate") or 0) for st in probe.get("streams", [])
                 if st.get("codec_type") == "audio"), 0) / 1000
    if kbps > 128:
        raise RuntimeError(f"{out.name} audio is {kbps:.0f} kbps, over Instagram's 128 kbps limit")
    info["size_bytes"] = size
    return info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dates", required=True, help="comma separated")
    ap.add_argument("--out", default="build-vertical")
    args = ap.parse_args(argv)

    profile = load_profile()
    cat = json.loads(Path(CATALOG_PATH).read_text(encoding="utf-8"))
    by_date = {d["date"]: d for d in cat["drops"]}
    want = [d.strip() for d in args.dates.split(",") if d.strip()]

    outdir = Path(args.out)
    (outdir / "work").mkdir(parents=True, exist_ok=True)
    made, failed = [], []

    for date in want:
        drop = by_date.get(date)
        if not drop:
            log(f"no drop for {date}")
            failed.append(date)
            continue
        work = outdir / "work" / date
        work.mkdir(parents=True, exist_ok=True)
        base = Path(drop["audio_url"]).name
        try:
            audio = RP.fetch(drop["audio_url"], work / base)
            name = base.replace(".mp3", "-vertical.mp4")
            d = outdir / f"{date}-vertical"
            d.mkdir(parents=True, exist_ok=True)
            info = vertical(drop, profile, audio, work, d / name)
        except Exception as exc:
            log(f"ERROR {date}: {exc}")
            failed.append(date)
            continue
        log(f"vertical: {date} {drop['title']:22} {name}  {info['width']}x{info['height']}  "
            f"{info['duration']:.0f}s  {info['size_bytes']/1e6:.0f}MB")
        made.append({"date": date, "dir": str(d), "file": name,
                     "title": f"{drop['title']} (Full Track)",
                     "duration": round(info["duration"], 1),
                     "size_mb": round(info["size_bytes"] / 1e6, 1)})

    (outdir / "made.json").write_text(json.dumps(made, indent=2), encoding="utf-8")
    log(f"vertical: made {len(made)}" + (f", failed {len(failed)}: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
