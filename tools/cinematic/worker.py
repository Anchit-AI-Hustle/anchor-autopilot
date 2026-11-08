"""Cinematic shots for the songbook, made on Anchit's Mac only while nobody is using it.

Anchit, 2026-11-08: "use LTX-Video or Wan or whatever is best and most efficient for my laptop;
ensure laptop speed never gets affected for other tasks". On the M5 Air (32 GB) LTX-Video 2B
(diffusers, Apple GPU, bf16) is the one that fits: Wan 2.2 needs over an hour for 2 s of video.
A warm LTX run held about 12 GB and took memory from 66% free to 28% while it ran, so it only
ever runs when the Mac is idle.

A LaunchAgent starts this every 10 minutes. It does nothing unless the Mac is free: on mains
power, untouched for IDLE_S, no song being made (ACE-Step or the Actions runner) and at least
MIN_FREE % of memory free. Before every denoising step it checks again (anyone touching the
keyboard or trackpad, the charger coming out, a song starting, memory pressure rising) and quits
at once, which frees the GPU and the memory; the shot it was on is simply made again next time.
It runs at background priority (taskpolicy -b in the LaunchAgent, nice 19 here).

Shots land in CLIPS/<song id>/shot-<n>.mp4 with shot-<n>.json beside it. anchor/cinematic.py cuts
them to the beat when a song has enough.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import zlib
from pathlib import Path

import tomllib

HOME = Path.home()
# its own clean clone of main, pulled at every run, so new storyboards and songs arrive by themselves
REPO = Path(os.environ.get("ANCHOR_REPO", HOME / "anchor-gpu" / "cinematic" / "repo"))
CLIPS = Path(os.environ.get("ANCHOR_CINEMATIC_DIR", HOME / "anchor-gpu" / "cinematic" / "clips"))
LOG = CLIPS.parent / "worker.log"
IDLE_S = int(os.environ.get("ANCHOR_CINEMATIC_IDLE_S", "600"))      # 10 minutes untouched
MIN_FREE = int(os.environ.get("ANCHOR_CINEMATIC_MIN_FREE", "45"))   # % memory free before loading the model
SHOTS = 6
# square, so the 16:9 and the 9:16 both crop from it and fill the screen (Anchit, 2026-11-09)
W, H, FRAMES, STEPS = 704, 704, 97, 30                             # about 4 s at 24 fps
MODEL = "Lightricks/LTX-Video"
NEG = "worst quality, inconsistent motion, blurry, jittery, distorted, deformed face, text, watermark, cartoon"
BUSY_PROCS = ("Runner.Worker", "ace-synth", "ace-lm", "ace-qwen", "anchor make", "anchor motion")


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False).stdout
    except Exception:  # noqa: BLE001
        return ""


def idle_seconds() -> float:
    m = re.search(r'"HIDIdleTime" = (\d+)', _run(["ioreg", "-c", "IOHIDSystem", "-d", "4"]))
    return int(m.group(1)) / 1e9 if m else 0.0


def on_mains() -> bool:
    return "AC Power" in _run(["pmset", "-g", "batt"])


def memory_free() -> int:
    m = re.search(r"free percentage: (\d+)%", _run(["memory_pressure"]))
    return int(m.group(1)) if m else 0


def pressure_level() -> int:
    """1 normal, 2 warning, 4 critical (the kernel's own view of memory pressure)."""
    try:
        return int(_run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]).strip() or 1)
    except ValueError:
        return 1


def song_being_made() -> bool:
    ps = _run(["ps", "-axo", "command"])
    return any(k in ps for k in BUSY_PROCS)


def why_not(running: bool = False) -> str | None:
    """None when the Mac is free for a shot, otherwise why not. While a shot is being made our own
    memory is in use, so the check then is the kernel's pressure level, not the free percentage."""
    if not on_mains():
        return "on battery"
    idle = idle_seconds()
    if idle < (IDLE_S if not running else 5):
        return f"in use ({idle:.0f}s idle)"
    if song_being_made():
        return "a song is being made"
    if running:
        if pressure_level() > 1:
            return "memory pressure rising"
    else:
        free = memory_free()
        if free < MIN_FREE:
            return f"memory {free}% free"
    return None


class Busy(Exception):
    pass


# the world each genre lives in (the picture fits the music: Anchit, 2026-11-09 "use appropriate
# music videos as per the music")
WORLD = {
    "hardtech": "at night in a big Indian city, sodium streetlights, wet roads, a warehouse rave with strobes and haze",
    "psy": "at dawn at an open-air forest festival, mist, colourful canopies, first sun through the trees",
    "rap": "in daylight city streets, flyovers, a crowded local train, concrete rooftops and water tanks",
    "hiphop": "in a neighbourhood at golden hour, a corner chai stall, a basketball court, a parked scooter",
}
# how each form moves: who is in the frame and what the last shot resolves into
FORM = {
    "story": ("the main person on an ordinary day", "the moment the story turns"),
    "revolt": ("a crowd gathering, people standing up together", "the crowd moving forward as one"),
    "argument": ("two people on opposite sides of a doorway", "the two of them finally side by side"),
    "confession": ("one person alone in a small room, a phone face down", "a window opening, morning light coming in"),
    "letter": ("a handwritten letter on a table, a person reading it", "the letter folded into a pocket, walking out"),
    "celebration": ("friends dancing and laughing together", "everyone jumping on the beat, arms up"),
    "vibe": ("people moving to music, lights and motion", "the dance floor at its peak"),
    "dialogue": ("two people talking across a table", "the two of them laughing together"),
    "mantra": ("a person sitting still while the world moves around them", "the sun rising over the crowd"),
}
# Outrun Your Shadow (model A) runs: fast handheld motion. Kindness Needs Truth (model B) argues: steadier, two sides.
CAMERA = {"A": ("fast handheld tracking", "whip pan", "running steadicam"),
          "B": ("slow push in", "steady locked-off frame", "slow lateral dolly")}


def storyboards() -> dict[str, list[dict]]:
    """Song id -> its storyboard (artist/songbook/storyboards/*.toml): twelve shots written from the
    lyrics, in story order, three of them the hook's image."""
    out = {}
    for p in sorted((REPO / "artist" / "songbook" / "storyboards").glob("*.toml")):
        for b in tomllib.loads(p.read_text()).get("boards", []):
            out[b["id"]] = b["shots"]
    return out


def shots(song: dict, boards: dict | None = None) -> list[dict]:
    """The song's shots: its storyboard when it has one, otherwise six from the template below."""
    board = (boards if boards is not None else storyboards()).get(song["id"])
    if board:
        return [{"prompt": b["prompt"], "part": b.get("part", ""), "hook": bool(b.get("hook"))} for b in board]
    return [{"prompt": p, "part": "", "hook": False} for p in template_shots(song)]


def template_shots(song: dict) -> list[str]:
    """Six shots that tell the song's story (its one-line subject) in its genre's world, framed for
    its form and moving like its model. People are seen from behind, in silhouette or small in
    frame: faces are the model's weakest part."""
    about = song["about"].rstrip(".")
    world = WORLD.get((song.get("groups") or ["hardtech"])[0], WORLD["hardtech"])
    who, end = FORM.get(song.get("form", "story"), FORM["story"])
    cam = CAMERA.get(song.get("model", "A"), CAMERA["A"])
    look = ("cinematic, 35mm film, realistic, natural light, shallow depth of field, gentle film grain, "
            "consistent colour grade")
    return [
        f"Wide establishing shot {world}. The song: {about}. Slow drone push in. {look}",
        f"Close-up of hands and small everyday objects that hold the story: {about}. {cam[1]}, {world}. {look}",
        f"{who.capitalize()}, seen from behind: {about}. {cam[0]}, {world}. {look}",
        f"Silhouette against a window or a streetlight, {who}: {about}. {cam[1]}. {look}",
        f"A crowd moment that shows what is at stake: {about}. {cam[2]}, slow motion, {world}. {look}",
        f"The final image, {end}: {about}. Slow crane up, {world}. {look}",
    ]


def songbook() -> list[dict]:
    """Songbook songs not yet released, in file order."""
    songs = []
    for p in sorted((REPO / "artist" / "songbook").glob("*.toml")):
        songs += tomllib.loads(p.read_text()).get("songs", [])
    try:
        used = {d.get("theme") for d in json.loads((REPO / "site" / "data" / "catalog.json").read_text())["drops"]}
    except Exception:  # noqa: BLE001
        used = set()
    return [s for s in songs if s["id"] not in used]


GROUP_OF = (("psy", "psy"), ("hip hop", "hiphop"), ("hiphop", "hiphop"), ("rap", "rap"))


def queued_cinematic() -> list[dict]:
    """Songs queued from the Sync with Suno page with the cinematic look, not released yet: they go
    out next, so they are shot first (template shots from the title, the tags and the first lines)."""
    try:
        q = json.loads((REPO / "queue" / "queue.json").read_text())
    except (OSError, ValueError):
        return []
    out = []
    for e in q.values():
        if e.get("style") != "cinematic" or not e.get("suno_id") or e.get("released"):
            continue
        tags = (e.get("tags") or "").lower()
        group = next((g for k, g in GROUP_OF if k in tags), "hardtech")
        first = " ".join(ln for ln in (e.get("lyrics") or "").splitlines() if ln and not ln.startswith("["))[:160]
        about = f"{e.get('title', '')}, {first}".strip(", ")
        out.append({"id": e["suno_id"], "about": about, "groups": [group], "form": "story", "model": "A"})
    return out


def todo() -> list[tuple[dict, int, dict]]:
    out, boards = [], storyboards()
    queued = queued_cinematic()
    for s in queued + songbook():
        for n, shot in enumerate(shots(s, boards), 1):
            if not (CLIPS / s["id"] / f"shot-{n:02d}.mp4").exists():
                out.append((s, n, shot))
    # songs closest to done first, so whole songs finish rather than every song half done
    left: dict[str, int] = {}
    for s, _, _ in out:
        left[s["id"]] = left.get(s["id"], 0) + 1
    first = {s["id"] for s in queued}
    return sorted(out, key=lambda x: (x[0]["id"] not in first, left[x[0]["id"]], x[0]["id"], x[1]))


def mark_complete(song: dict) -> None:
    """A ``complete`` file once every shot of the song exists: the daily run then prefers it."""
    want = len(shots(song))
    d = CLIPS / song["id"]
    if all((d / f"shot-{n:02d}.mp4").exists() for n in range(1, want + 1)):
        (d / "complete").write_text(time.strftime("%Y-%m-%d %H:%M:%S\n"))


def main() -> int:
    reason = why_not()
    if reason:
        log(f"skip: {reason}")
        return 0
    if (REPO / ".git").exists():
        _run(["git", "-C", str(REPO), "pull", "-q", "--ff-only"])
    jobs = todo()
    if not jobs:
        log("skip: every unreleased song has its shots")
        return 0
    os.nice(19)
    import torch
    from diffusers import LTXPipeline
    from diffusers.utils import export_to_video

    def guard(pipe, step, t, kw):
        r = why_not(running=True)
        if r:
            raise Busy(r)
        return kw

    t0 = time.time()
    pipe = LTXPipeline.from_pretrained(MODEL, torch_dtype=torch.bfloat16).to("mps")
    pipe.vae.enable_tiling()
    log(f"loaded in {time.time() - t0:.0f}s; {len(jobs)} shots to make")
    total: dict[str, int] = {}
    for song, n, _ in jobs:
        total[song["id"]] = max(total.get(song["id"], 0), n)
    for song, n, shot in jobs:
        r = why_not(running=True)
        if r:
            log(f"stop: {r}")
            return 0
        out = CLIPS / song["id"] / f"shot-{n:02d}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        seed = zlib.crc32(f"{song['id']}/{n}".encode()) % 2**31
        t1 = time.time()
        try:
            frames = pipe(prompt=shot["prompt"], negative_prompt=NEG, width=W, height=H, num_frames=FRAMES,
                          num_inference_steps=STEPS, guidance_scale=3.0,
                          generator=torch.Generator().manual_seed(seed),
                          callback_on_step_end=guard).frames[0]
        except Busy as exc:
            log(f"stop: {exc} (during {song['id']} shot {n}); GPU and memory released")
            return 0
        tmp = out.with_name(out.stem + ".part.mp4")
        export_to_video(frames, str(tmp), fps=24)
        tmp.rename(out)
        took = time.time() - t1
        out.with_suffix(".json").write_text(json.dumps({**shot, "seed": seed, "size": [W, H], "frames": FRAMES,
                                                         "steps": STEPS, "model": MODEL, "seconds": round(took)}))
        log(f"made {song['id']} shot {n} in {took:.0f}s")
        mark_complete(song)
    return 0


if __name__ == "__main__":
    sys.exit(main())
