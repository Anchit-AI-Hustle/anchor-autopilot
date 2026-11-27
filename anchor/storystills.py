"""Storyline shots made from still frames, so every song can have a story video, not only the songs
the Mac had time to film.

2026-11-28 audit: the Mac's LTX-Video worker (tools/cinematic/worker.py) runs only while the Mac
sits idle on the charger, and in three weeks it filmed one song (ashes-for-a-throne). Its shots
also live only on the Mac, so a song rendered on GitHub's CPU could never use them. Every video
fell back to the motion-graphics scene video (scenes.py).

This module makes the song's storyboard (artist/songbook/storyboards/*.toml: twelve shots written
from the lyrics, in lyric order, three of them the hook) into shots the cinematic cut
(cinematic.py) already knows how to use:

* one photoreal frame per storyboard shot, from the first image provider that is set up:
  Cloudflare Workers AI FLUX.1 schnell (``CF_ACCOUNT_ID`` + ``CF_API_TOKEN``, free daily quota),
  then Pollinations FLUX with an account token (``POLLINATIONS_TOKEN``, which also removes their
  watermark). Without a key nothing is made and the video stays the scene video: anonymous
  Pollinations frames carry a watermark, and cropping it off would get around their terms.
* each frame becomes a four-second square shot that moves the way its prompt says the camera
  moves (push in, pull back or crane up, tracking or orbit, handheld), with a slow drift and
  a little film flicker, so the cut on the beat feels filmed rather than a slideshow
* shot-NN.mp4 + shot-NN.json (part, hook, source) land in the song's folder, exactly like the
  worker's, and a ``complete`` file marks the set as whole
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import tomllib
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

from .config import env
from .util import log

ROOT = Path(__file__).resolve().parent.parent
BOARDS = ROOT / "artist" / "songbook" / "storyboards"
SIZE = 1080                # square: the 16:9 and the 9:16 both crop from it (as the LTX shots)
SECONDS = 4.0
FPS = 30
# the storyboards already end on "cinematic, 35mm film, realistic ..."; this keeps stills clean
STILL_SUFFIX = ", photograph, film still, no text, no letters, no logo, no watermark"


def stills_dir() -> Path:
    """Where still-made shots are kept: next to the Mac's clips when set, else under build/."""
    return Path(env("ANCHOR_STILLS_DIR", "") or ROOT / "build" / "story-shots")


def board(song_id: str | None, boards_dir: Path = BOARDS) -> list[dict]:
    """The song's storyboard shots in order, or [] when it has none."""
    if not song_id:
        return []
    for p in sorted(boards_dir.glob("*.toml")):
        for b in tomllib.loads(p.read_text()).get("boards", []):
            if b.get("id") == song_id:
                return [{"prompt": s["prompt"], "part": s.get("part", ""), "hook": bool(s.get("hook"))}
                        for s in b.get("shots", [])]
    return []


# ----------------------------------------------------------------------------- image providers
def _cloudflare(prompt: str, seed: int):
    from .art import cloudflare_flux
    return cloudflare_flux(prompt, seed, env("CF_ACCOUNT_ID"), env("CF_API_TOKEN"))


def _pollinations(prompt: str, seed: int, timeout: int = 180):
    from PIL import Image
    q = urllib.parse.urlencode({"width": 1024, "height": 1024, "seed": seed, "model": "flux",
                                "nologo": "true", "private": "true", "token": env("POLLINATIONS_TOKEN")})
    url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt[:1500])}?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "anchor-autopilot"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if not (resp.headers.get("Content-Type") or "").startswith("image/"):
            raise RuntimeError(f"Pollinations returned {resp.headers.get('Content-Type')}")
        img = Image.open(io.BytesIO(resp.read())).convert("RGB")
    if min(img.size) < 512:
        raise RuntimeError(f"Pollinations returned a tiny image {img.size}")
    return img


def providers() -> list[tuple[str, object]]:
    """The image providers that are set up, best first. Empty: no story stills on this run."""
    out = []
    if env("CF_ACCOUNT_ID") and env("CF_API_TOKEN"):
        out.append(("cloudflare-flux-schnell", _cloudflare))
    if env("POLLINATIONS_TOKEN"):
        out.append(("pollinations-flux", _pollinations))
    return out


# Camera directions are for video models. An image model draws them as things: "steady slow crane
# up" came back as a construction crane on the rooftop (2026-11-28, Guarding Your Flame shot 8).
# The move itself is still read from the full prompt (move_for); the still gets only the scene.
CAMERA_VOCAB = set("""
handheld camera shot steady locked off frame wide close extreme up push pushing pull pulling back in forward
crane down over orbit orbiting circle circling tracking track follow following whip pan panning drift drifting
tilt tilting rise rising rises jerking shaking rocking settling slow slowly fast quick low angle gentle sweeping
motion speed full upward downward small move moving zoom dolly""".split())
FILLER = {"a", "an", "the", "with", "at", "to", "of", "and", "into", "from", "their", "his", "her", "heads", "behind"}


def scene_only(prompt: str) -> str:
    """The prompt without the clauses made only of camera directions, for a still. A clause that
    also names the scene ("handheld tracking shot behind a figure striding down a corridor") stays."""
    keep = []
    for c in (x.strip() for x in prompt.split(",")):
        words = re.findall(r"[a-z]+", c.lower())
        if not words:
            continue
        if any(w in CAMERA_VOCAB for w in words) and all(w in CAMERA_VOCAB or w in FILLER for w in words):
            continue
        keep.append(c)
    return ", ".join(keep)


def still(prompt: str, seed: int, dest: Path, chain: list | None = None) -> str | None:
    """One frame for one shot, saved as ``dest`` (JPEG). Returns the provider's name, or None."""
    for name, fn in (providers() if chain is None else chain):
        for attempt in range(2):
            try:
                img = fn(scene_only(prompt) + STILL_SUFFIX, seed + attempt)
                dest.parent.mkdir(parents=True, exist_ok=True)
                img.save(dest, quality=93)
                return name
            except Exception as exc:          # noqa: BLE001 - next attempt, then next provider
                log(f"story still: {name} failed ({str(exc)[:140]})")
    return None


# ----------------------------------------------------------------------------- camera moves
def move_for(prompt: str) -> str:
    """The camera move a shot's prompt asks for, as one of the moves ``animate`` knows."""
    p = prompt.lower()
    if any(w in p for w in ("pull back", "pulls back", "crane up", "crane over", "rises", "rising",
                            "drone", "widening", "slow crane")):
        return "pull"
    if any(w in p for w in ("orbit", "circle", "tracking", "sweeping", "pan ", "panning", "tracks")):
        return "track"
    if "push in" in p:
        return "push"
    if any(w in p for w in ("whip", "shaking", "shake", "bouncing", "fast handheld", "quick handheld")):
        return "shake"
    return "push"


def zoompan(move: str, frames: int, size: int, seed: int) -> str:
    """The ffmpeg zoompan + crop expression for one move. Frames come from an image scaled up 4x
    first, so the slow sub-pixel drift does not judder."""
    n = frames
    flip = 1 if seed % 2 else -1
    if move == "pull":
        z = f"1.22-0.20*on/{n}"
        x, y = "iw/2-(iw/zoom/2)", f"ih/2-(ih/zoom/2)+ih*0.04*(1-on/{n})"
    elif move == "track":
        z = "1.16"
        x, y = f"(iw-iw/zoom)*(0.5+{flip}*0.42*(on/{n}-0.5))", "ih/2-(ih/zoom/2)"
    elif move == "shake":
        z = f"1.12+0.08*on/{n}"
        x = f"iw/2-(iw/zoom/2)+iw*0.006*sin(on*1.9+{seed % 7})"
        y = f"ih/2-(ih/zoom/2)+ih*0.006*cos(on*2.3+{seed % 5})"
    else:  # push
        z = f"1.0+0.18*on/{n}"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    return f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={size}x{size}:fps={FPS}"


def animate(image: Path, out: Path, move: str, seed: int, seconds: float = SECONDS, size: int = SIZE,
            timeout: int = 600) -> Path:
    """A ``seconds`` long square shot from one still, moving the way the storyboard asks."""
    frames = int(round(seconds * FPS))
    # film feel: a touch of grain and a soft, slow flicker in brightness
    vf = (f"scale={size * 4}:{size * 4}:flags=lanczos,{zoompan(move, frames, size, seed)},"
          f"eq=brightness='0.012*sin(2*PI*t*0.9)':eval=frame,noise=alls=6:allf=t,format=yuv420p")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.mp4")
    cmd = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(image), "-vf", vf, "-frames:v", str(frames),
           "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", str(tmp)]
    subprocess.run(cmd, check=True, timeout=timeout)
    tmp.replace(out)
    return out


# ----------------------------------------------------------------------------- the whole set
def ensure(song_id: str | None, dest_root: Path | None = None, chain: list | None = None,
           stills_from: Path | None = None) -> list[Path]:
    """The song's still-made shots, making whatever is missing. Returns the shots in order, or []
    when the song has no storyboard or no frame could be made for enough of it.

    ``stills_from``: a folder of ready frames (still-NN.jpg) to use instead of a provider, for
    frames made elsewhere."""
    from .cinematic import MIN_SHOTS
    shots = board(song_id)
    if not shots:
        return []
    chain = providers() if chain is None else chain
    if not chain and not stills_from:
        log("story stills: no image provider set up (CF_ACCOUNT_ID + CF_API_TOKEN, or POLLINATIONS_TOKEN)")
        return []
    d = (dest_root or stills_dir()) / song_id
    made: list[Path] = []
    for n, s in enumerate(shots, 1):
        mp4, meta, jpg = d / f"shot-{n:02d}.mp4", d / f"shot-{n:02d}.json", d / f"still-{n:02d}.jpg"
        seed = zlib.crc32(f"{song_id}:{n}".encode()) % 2_000_000_000
        if not (mp4.exists() and mp4.stat().st_size > 10_000):
            src = (stills_from / f"still-{n:02d}.jpg") if stills_from else None
            if src is not None and src.exists():
                d.mkdir(parents=True, exist_ok=True)
                jpg.write_bytes(src.read_bytes())
                provider = "supplied"
            elif not jpg.exists():
                provider = still(s["prompt"], seed, jpg, chain)
                if provider is None:
                    continue
            else:
                provider = "cached"
            move = move_for(s["prompt"])
            animate(jpg, mp4, move, seed)
            meta.write_text(json.dumps({"part": s["part"], "hook": s["hook"], "source": "stills",
                                        "provider": provider, "move": move, "prompt": s["prompt"]}, indent=1))
        made.append(mp4)
    if len(made) == len(shots):
        (d / "complete").write_text("stills\n")
    log(f"story stills: {song_id}: {len(made)} of {len(shots)} shots")
    return made if len(made) >= MIN_SHOTS else []


def render_for_drop(drop: dict, out_dir: Path, stills_from: Path | None = None, audio: Path | None = None,
                    vertical: bool = True) -> dict:
    """The storyline video of a released drop (catalog entry): its storyboard made into shots, cut to
    its master on the beat with its timed lyrics. 16:9, and 9:16 when ``vertical``. Raises when the
    song has no storyboard or too few shots could be made."""
    from . import cinematic, lyrics as lyr
    from .ledger import clean_title
    from .scenes import song_sections
    from .video import master_beat_offset
    song_id = drop.get("theme")
    out_dir.mkdir(parents=True, exist_ok=True)
    shots = ensure(song_id, out_dir / "shots", stills_from=stills_from)
    if not shots:
        raise RuntimeError(f"{drop.get('title')}: no storyboard or too few shots for a story video")
    if audio is None:
        audio = out_dir / "master.mp3"
        if not audio.exists():
            with urllib.request.urlopen(drop["audio_url"], timeout=300) as r:
                audio.write_bytes(r.read())
    bpm = float(drop["bpm"])
    offset = master_beat_offset(audio, bpm)
    secs = song_sections(audio, bpm, offset)
    sung = drop.get("lyrics") or ""
    lines = lyr.lines_for(audio, out_dir / "lyrics", known=sung or None, title=drop.get("title"))
    title, sub = clean_title(drop["title"]), drop.get("lane_name") or ""
    accent = drop.get("accent") or "#ff8a3d"
    base = Path(drop["audio_url"]).stem if drop.get("audio_url") else song_id
    out = {"shots": len(shots), "lines": len(lines), "sections": len(secs)}
    for fmt, vert in (("169", False), ("916", True)):
        if vert and not vertical:
            continue
        f = out_dir / f"{base}-story-{fmt}.mp4"
        info = cinematic.render_cinematic_video(shots, audio, f, accent, secs, title, sub, out_dir / f"work-{fmt}",
                                                bpm=bpm, beat_offset=offset, lines=lines, vertical=vert,
                                                crf=21 if not vert else 23, lyrics=sung)
        out[fmt] = {"file": str(f), **info}
    return out


def main(argv: list[str]) -> int:
    """python -m anchor.storystills SONG_ID [--from DIR]: make (or finish) one song's shots.
    python -m anchor.storystills --drop DROP_ID --out DIR [--from DIR] [--audio FILE] [--no-vertical]:
    the storyline video of a released drop."""
    if not argv:
        print(main.__doc__)
        return 2
    def opt(name):
        return Path(argv[argv.index(name) + 1]) if name in argv else None
    src = opt("--from")
    if "--drop" in argv:
        from . import catalog
        drop_id = argv[argv.index("--drop") + 1]
        drop = next((d for d in catalog.load()["drops"] if d.get("id") == drop_id), None)
        if drop is None:
            print(f"no drop {drop_id} in the catalog")
            return 2
        res = render_for_drop(drop, opt("--out") or ROOT / "build" / "story" / drop_id, stills_from=src,
                              audio=opt("--audio"), vertical="--no-vertical" not in argv)
        print(json.dumps(res, default=str))
        return 0
    shots = ensure(argv[0], stills_from=src)
    print(json.dumps({"song": argv[0], "shots": [str(p) for p in shots]}))
    return 0 if shots else 1


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
