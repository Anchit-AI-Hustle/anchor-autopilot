"""Cinematic music videos: real filmed-looking shots of the song's story, cut to the beat.

Anchit, 2026-11-08: "see if real cinematic videos as per theme can be created", then "use
LTX-Video or Wan or whatever is best and most efficient for my laptop; ensure laptop speed never
gets affected for other tasks". ``tools/cinematic/worker.py`` makes the shots on the Mac with
LTX-Video, only while nobody is using it, six per songbook song, staged from the song's own
one-line subject. This module turns them into the song's video:

* every cut lands on a bar line; energetic sections cut every 2 bars, calm ones (intro, outro,
  breakdown) hold up to 4 bars and play a little slower
* the shots rotate so the same one never plays twice in a row, alternating which part of the shot
  is shown and mirroring it on every other pass, so six shots carry a whole song
* the lyrics (the same kinetic karaoke as the scene videos), the progress bar, a film grade,
  grain and a vignette go on top; the 9:16 shows the 16:9 picture over a blurred fill

When a song has fewer than ``MIN_SHOTS`` shots the pipeline keeps the scene video (scenes.py).
"""
from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path

from .util import log

FPS = 30
MIN_SHOTS = 4
CALM = {"intro", "outro", "breakdown"}
CALM_SPEED = 0.8                     # calm sections play a little slower, energetic ones at speed


def clips_dir() -> Path:
    return Path(os.environ.get("ANCHOR_CINEMATIC_DIR", Path.home() / "anchor-gpu" / "cinematic" / "clips"))


def shots_for(song_id: str | None, directory: Path | None = None) -> list[Path]:
    """The finished shots of a songbook song, in order; [] when there are too few to carry a video."""
    if not song_id:
        return []
    d = (directory or clips_dir()) / song_id
    shots = sorted(p for p in d.glob("shot-*.mp4") if ".part" not in p.name and p.stat().st_size > 10_000)
    return shots if len(shots) >= MIN_SHOTS else []


def plan(secs: list[dict], duration: float, bpm: float, offset: float, n_shots: int,
         shot_len: float) -> list[dict]:
    """The edit: contiguous segments covering the song, every cut on a bar line.

    Each segment: start/end (song seconds), first/last frame, the shot, where in the shot it
    starts (frame at 30 fps after the speed change), the speed and whether it is mirrored."""
    bar = 240.0 / bpm
    cuts: list[tuple[float, str]] = []
    for s in secs or [{"start": 0.0, "end": duration, "kind": "groove"}]:
        a, b, kind = max(0.0, s["start"]), min(duration, s["end"]), s["kind"]
        speed = CALM_SPEED if kind in CALM else 1.0
        usable = shot_len / speed - 0.15
        bars = max(1, min(4 if kind in CALM else 2, int(usable // bar)))
        t = a
        while t < b - 0.05:
            cuts.append((t, kind))
            # the next bar line at least ``bars`` bars on (the beat grid starts at ``offset``)
            k = math.floor((t - offset) / bar + 1e-6) + bars
            while k > 1 and offset + bar * k - t > usable:           # never longer than the shot
                k -= 1
            nxt = offset + bar * k
            t = nxt if nxt > t + 0.25 else t + min(bar * bars, usable)
    cuts.sort()
    total = round(duration * FPS)
    starts = [round(c[0] * FPS) for c in cuts]
    starts[0] = 0
    out, order, last = [], list(range(n_shots)), -1
    for k, (n0, (t, kind)) in enumerate(zip(starts, cuts)):
        n1 = starts[k + 1] if k + 1 < len(starts) else total
        if n1 <= n0:
            continue
        shot = order[k % n_shots]
        if shot == last and n_shots > 1:
            shot = order[(k + 1) % n_shots]
        rnd = k // n_shots
        speed = CALM_SPEED if kind in CALM else 1.0
        room = int((shot_len / speed) * FPS) - (n1 - n0) - 2
        src = 0 if rnd % 2 == 0 or room <= 0 else room          # alternate the head and the tail of the shot
        out.append({"start": n0 / FPS, "end": n1 / FPS, "n0": n0, "n1": n1, "shot": shot, "src": max(0, src),
                    "speed": speed, "flip": rnd % 4 in (1, 2), "kind": kind})
        last = shot
    return out


def _shot_len(p: Path) -> float:
    from .video import media_summary
    return float(media_summary(p)["duration"])


def render_cinematic_video(shots: list[Path], audio: Path, out: Path, accent: str, secs: list[dict], title: str,
                           sub: str, work: Path, *, bpm: float, beat_offset: float, lines: list[dict] | None = None,
                           vertical: bool = False, crf: int = 23, timeout: int = 5400) -> dict:
    """The song's cinematic video, verified against the audio length."""
    from .scenes import _fonts, write_ass
    from .video import AAC_CLEAN, _ff, media_summary

    duration = media_summary(audio)["duration"]
    W, H = (1080, 1920) if vertical else (1920, 1080)
    work.mkdir(parents=True, exist_ok=True)
    shot_len = min(_shot_len(p) for p in shots)
    edit = plan(secs, duration, bpm, beat_offset, len(shots), shot_len)
    ass = write_ass(work / "cinematic.ass", accent, W, H, secs, lines or [], title, sub)
    # the edit, one small exact-length piece per cut, then joined without re-encoding: one ffmpeg
    # graph holding every cut would buffer each cut's frames until its turn (it ran out of memory)
    pieces = []
    for k, seg in enumerate(edit):
        n = seg["n1"] - seg["n0"]
        flip = ",hflip" if seg["flip"] else ""
        piece = work / f"cut-{k:03d}.mp4"
        vf = (f"setpts=(PTS-STARTPTS)/{seg['speed']},fps={FPS},tpad=stop_mode=clone:stop_duration=6,"
              f"trim=start_frame={seg['src']}:end_frame={seg['src'] + n},setpts=PTS-STARTPTS,"
              f"scale=1280:720:force_original_aspect_ratio=increase:flags=lanczos,crop=1280:720{flip},setsar=1")
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-v", "error", "-i", str(Path(shots[seg["shot"]]).resolve()),
                        "-vf", vf, "-frames:v", str(n), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
                        "-pix_fmt", "yuv420p", "-r", str(FPS), str(piece)], check=True, timeout=300)
        pieces.append(piece)
    (work / "cuts.txt").write_text("".join(f"file '{p.name}'\n" for p in pieces))
    body = work / "body.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-v", "error", "-f", "concat", "-safe", "0", "-i", "cuts.txt",
                    "-c", "copy", str(body)], check=True, cwd=str(work), timeout=600)
    g = ["[0:v]scale=1920:1080:flags=lanczos,setsar=1,format=yuv420p[raw]"]
    g.append("[raw]eq=contrast=1.06:saturation=1.05:brightness=0.0,noise=alls=5:allf=t[film]")
    if vertical:
        g.append("[film]split[fa][fb]")
        g.append(f"[fa]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:2,"
                 f"eq=brightness=-0.18[bg]")
        g.append(f"[fb]scale={W}:-2:flags=lanczos[fg]")
        g.append("[bg][fg]overlay=x=0:y=(H-h)/2[body]")
    else:
        g.append("[film]null[body]")
    a = _ff(accent)
    g.append(f"color=c={a}:s={W}x8:r={FPS}[fill]")
    g.append(f"color=c=0x0a1622:s={W}x8:r={FPS}[track]")
    g.append(f"[track][fill]overlay=x='-{W}+{W}*t/{duration:.3f}':y=0:shortest=1[bar]")
    g.append(f"[body][bar]overlay=x=0:y={H - 8}:shortest=1,vignette=PI/5,"
             f"subtitles={ass.name}:fontsdir={_fonts()},format=yuv420p[vout]")
    graph = ";".join(g)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "error", "-i", str(body.resolve()),
           "-i", str(Path(audio).resolve()), "-filter_complex", graph, "-map", "[vout]", "-map", "1:a",
            "-t", f"{duration:.3f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-maxrate", "6M", "-bufsize", "12M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", *AAC_CLEAN,
            "-ar", "48000", "-movflags", "+faststart", str(Path(out).resolve())]
    log(f"cinematic: {len(edit)} cuts from {len(shots)} shots, {W}x{H}")
    errf = work / "ffmpeg.err"
    with open(errf, "wb") as ef:
        code = subprocess.run(cmd, stderr=ef, cwd=str(work), timeout=timeout, check=False).returncode
    if code != 0:
        raise RuntimeError(f"cinematic render failed ({code}): " + errf.read_text(errors="replace")[-1500:])
    info = media_summary(out)
    if abs(info["duration"] - duration) > 1.5:
        raise RuntimeError(f"cinematic render truncated: {info['duration']:.1f}s vs audio {duration:.1f}s")
    for p in pieces:
        p.unlink(missing_ok=True)
    return {**info, "cuts": len(edit), "shots": len(shots), "look": "cinematic"}
