"""Motion-graphics videos for every released song, not only the new ones.

``python -m anchor motion --list`` prints the songs that have a master on a GitHub release;
``--id 2026-09-28 --out build/motion`` renders that song's 16:9 (beat punch-in, live spectrum)
and its whole-track 9:16 (the Short's hologram design, beat-pulsed), and ``--upload`` puts both
on the song's release in place of the old still-frame videos. The motion workflow runs it once
per song, in parallel.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import fullvideos, lyrics, scenes
from .config import CATALOG_PATH, Profile
from .util import log, read_json
from .versions import RELEASES, fetch
from .video import master_beat_offset


LEGACY_PATH = CATALOG_PATH.parent / "legacy_motion.json"


def songs(catalog: dict, legacy_path: Path | None = None) -> list[dict]:
    """Every robot drop whose master is on its release, newest first, then the older songs
    listed in site/data/legacy_motion.json (full videos on the channel from before the robot)."""
    out = [d for d in catalog.get("drops", []) if d.get("audio_url") and d.get("bpm") and d.get("family")]
    out = sorted(out, key=lambda d: d.get("date") or d["id"], reverse=True)
    have = {d["id"] for d in out}
    legacy = (read_json(legacy_path or LEGACY_PATH, {}) or {}).get("songs", [])
    return out + [d for d in legacy if d["id"] not in have and d.get("audio_url") and d.get("bpm") and d.get("family")]


ONLY_PATH = CATALOG_PATH.parent / "motion_only.json"
# 2: every movement (turns, scrolls, particles) surges on the kick instead of drifting at a constant
# speed, and karaoke words light when they are sung (they lit 0.2 s early). Uploads wait for it.
# 3: a sung line leaves the screen 1.2 s after its last word (it stayed up through whole
# instrumental stretches), and no word lights for more than 2 s.
RENDER = 3


def list_ids(catalog: dict, only_path: Path | None = None) -> list[str]:
    """The songs a full motion run renders: every song, or only the ids in site/data/motion_only.json
    when that lists any (a top-up run for songs added later, without re-rendering the rest)."""
    ids = [d["id"] for d in songs(catalog)]
    only = (read_json(only_path or ONLY_PATH, {}) or {}).get("ids") or []
    return [i for i in ids if i in only] if only else ids


def render_song(profile: Profile, r: dict, repo: str, work: Path) -> dict:
    """The two videos for one song, verified against its audio length. Returns their paths."""
    work.mkdir(parents=True, exist_ok=True)
    video169, _frame = fullvideos.build(profile, r, repo, work)
    base = video169.name.removesuffix("-full-169.mp4")
    mp3 = next(work.glob(f"{base}.*"))
    cover = work / f"{base}-cover.jpg"
    if not cover.exists():                                   # build() fell back to the site copy
        from .config import SITE
        cover = SITE / r["cover"]
    fam = profile.family(r["family"])
    video916 = work / f"{base}-full-916.mp4"
    bpm = float(r["bpm"])
    offset = master_beat_offset(mp3, bpm)
    lines = lyrics.lines_for(mp3, work / "lyrics", r.get("lyrics"), fullvideos.clean_title(r["title"]))
    sub = f"{r.get('lane_name') or 'Techno'}"               # no tempo on any listener surface
    art = work / f"{base}-art-raw.jpg"
    info = scenes.render_scene_video(scenes.square(art if art.exists() else cover, work / "tex-v.jpg"), mp3, video916,
                                     r.get("accent") or fam.accent, scenes.song_sections(mp3, bpm, offset),
                                     fullvideos.clean_title(r["title"]), sub, work / "scene-work-v", bpm=bpm,
                                     beat_offset=offset, lines=lines, vertical=True, crf=24)
    frame = work / f"{base}-motion-frame-169.jpg"
    if _frame and Path(_frame).exists():
        shutil.copyfile(_frame, frame)
    marker = work / f"{base}-motion.json"
    marker.write_text(json.dumps({"id": r["id"], "lyrics_lines": len(lines), "bpm_on_screen": False, "render": RENDER}))
    return {"id": r["id"], "full_169": video169, "full_916": video916, "tag": f"drop-{r['id']}", "reel": info,
            "lyrics": len(lines), "extras": [p for p in (frame, marker) if p.exists()]}


def upload(repo: str, tag: str, files: list[Path]) -> None:
    """Replace the release's still-frame videos (same file names) with the motion ones. An older
    song has no release yet, so one is made for it first."""
    if subprocess.run(["gh", "release", "view", tag, "--repo", repo], capture_output=True).returncode != 0:
        subprocess.run(["gh", "release", "create", tag, "--repo", repo, "--title", tag,
                        "--notes", "Motion video for an older song (site/data/legacy_motion.json)."], check=True)
    subprocess.run(["gh", "release", "upload", tag, *map(str, files), "--clobber", "--repo", repo], check=True)
    log(f"motion: {tag}: {', '.join(f.name for f in files)} uploaded")


def run(profile: Profile, *, repo: str, song_id: str, work: Path, do_upload: bool,
        catalog_path: Path = CATALOG_PATH) -> dict:
    catalog = read_json(catalog_path, {}) or {}
    r = next((d for d in songs(catalog) if d["id"] == song_id), None)
    if r is None:
        raise SystemExit(f"motion: no released song with id {song_id}")
    done = render_song(profile, r, repo, work)
    if do_upload:
        upload(repo, done["tag"], [done["full_169"], done["full_916"], *done["extras"]])
    return {"id": done["id"], "full_169": done["full_169"].name, "full_916": done["full_916"].name,
            "uploaded": do_upload}
