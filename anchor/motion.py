"""Motion-graphics videos for every released song, not only the new ones.

``python -m anchor motion --list`` prints the songs that have a master on a GitHub release;
``--id 2026-09-28 --out build/motion`` renders that song's 16:9 (beat punch-in, live spectrum)
and its whole-track 9:16 (the Short's hologram design, beat-pulsed), and ``--upload`` puts both
on the song's release in place of the old still-frame videos. The motion workflow runs it once
per song, in parallel.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import fullvideos, lyrics, scenes
from .config import CATALOG_PATH, Profile
from .util import log, read_json
from .versions import RELEASES, fetch
from .video import master_beat_offset


def songs(catalog: dict) -> list[dict]:
    """Every robot drop whose master is on its release, newest first."""
    out = [d for d in catalog.get("drops", []) if d.get("audio_url") and d.get("bpm") and d.get("family")]
    return sorted(out, key=lambda d: d.get("date") or d["id"], reverse=True)


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
    lines = lyrics.lines_for(mp3, work / "lyrics", r.get("lyrics"))
    sub = f"{r.get('lane_name') or 'Techno'} {int(round(bpm))} BPM"
    art = work / f"{base}-art-raw.jpg"
    info = scenes.render_scene_video(scenes.square(art if art.exists() else cover, work / "tex-v.jpg"), mp3, video916,
                                     r.get("accent") or fam.accent, scenes.song_sections(mp3, bpm, offset),
                                     fullvideos.clean_title(r["title"]), sub, work / "scene-work-v", bpm=bpm,
                                     beat_offset=offset, lines=lines, vertical=True, crf=24)
    return {"id": r["id"], "full_169": video169, "full_916": video916, "tag": f"drop-{r['id']}", "reel": info, "lyrics": len(lines)}


def upload(repo: str, tag: str, files: list[Path]) -> None:
    """Replace the release's still-frame videos (same file names) with the motion ones."""
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
        upload(repo, done["tag"], [done["full_169"], done["full_916"]])
    return {"id": done["id"], "full_169": done["full_169"].name, "full_916": done["full_916"].name,
            "uploaded": do_upload}
