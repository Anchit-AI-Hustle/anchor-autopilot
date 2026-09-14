"""End-to-end stages used by the CLI and the GitHub Actions workflow."""
from __future__ import annotations

import re
import shutil
from datetime import date as Date, datetime, timedelta, timezone
from pathlib import Path

from . import catalog
from .art import make_cover, og_card
from .audio import (analyze, beat_phase, best_window, cut, decode, encode_flac, encode_mp3,
                    estimate_key, master, quality_gate)
from .brief import describe, make_brief, post_time
from .config import CATALOG_PATH, SITE, STATUS_PATH, Profile, env
from .music import get_engine
from .queue import QUEUE, mark_done, next_track
from .publish import Buffer, BufferError, build_post_input, schedule_for, verify_media_url
from .util import iso, log, read_json, utcnow, write_json
from .video import poster_frame, render_short


class QualityError(RuntimeError):
    pass


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def asset_base(profile: Profile, brief: dict) -> str:
    return f"{profile.artist['name']}-{brief['date']}-{slug(brief['title'])}"


# ------------------------------------------------------------------------- make
def make(profile: Profile, day: str, out_dir: Path, *, engine_name: str | None = None,
         art_mode: str | None = None, retries: int = 1, catalog_path: Path = CATALOG_PATH,
         queue_dir: Path | None = None, use_queue: bool = True) -> dict:
    # resolved here, not in the signature, so tests can point the queue somewhere empty
    queue_dir = queue_dir or QUEUE
    out_dir.mkdir(parents=True, exist_ok=True)
    hist = catalog.history(catalog.load(catalog_path))
    # use_queue=False exercises the generator even when tracks are waiting - the only way
    # to hear what the model does without spending a queued release to find out
    queued = next_track(queue_dir) if use_queue and engine_name not in ("fixture",) else None
    if queued:
        return make_from_queue(profile, day, out_dir, queued, art_mode=art_mode, hist=hist)
    engine = get_engine(profile.music, engine_name)
    attempts_log = []
    for attempt in range(retries + 1):
        brief = make_brief(profile, day, hist, attempt)
        log(f"brief: {brief['title']!r} | {brief['lane_name']} | {brief['bpm']} BPM | {brief['key']} | "
            f"{brief['family_name']} | seed {brief['seed']}")
        raw, stats = engine.generate(brief, out_dir / f"gen-{attempt}")
        stats_audio = analyze(decode(raw))
        ok, fails, warns = quality_gate(stats_audio, brief)
        attempts_log.append({"attempt": attempt, "seed": brief["seed"], "ok": ok, "fail": fails, "warn": warns})
        log(f"QC attempt {attempt}: {'PASS' if ok else 'FAIL'} {fails or ''} {warns or ''}")
        if ok:
            break
    else:
        raise QualityError(f"track failed QC after {retries + 1} attempts: {attempts_log}")

    # the model treats BPM as guidance; publish the tempo the track actually has
    est = stats_audio.get("bpm_est")
    if est and abs(est - brief["bpm"]) > 1.0:
        log(f"tempo landed at {est} BPM (asked {brief['bpm']}); metadata follows the audio")
        brief["bpm_requested"] = brief["bpm"]
        brief["bpm"] = int(round(est))
        brief.update(describe(profile, brief))

    # same for the key: the model takes it as a hint, so publish what it actually played
    heard = estimate_key(decode(raw).mean(axis=1))
    if heard:
        key, confidence = heard
        brief["key_confidence"] = confidence
        if confidence < 0.25:
            attempts_log[-1]["warn"] = list(attempts_log[-1].get("warn") or []) + \
                ["key is not clearly audible; kept the requested one"]
        elif key != brief["key"]:
            log(f"key landed on {key} (asked {brief['key']}); metadata follows the audio")
            brief["key_requested"] = brief["key"]
            brief["key"] = key
            brief.update(describe(profile, brief))

    return finish(profile, brief, raw, stats_audio, stats, attempts_log, out_dir, art_mode)


def finish(profile: Profile, brief: dict, raw: Path, stats_audio: dict, stats: dict,
           attempts_log: list, out_dir: Path, art_mode: str | None) -> dict:
    """Master, cut the Short, draw the cover, render the video, write the drop files."""
    base = asset_base(profile, brief)
    master_wav = out_dir / "master.wav"
    loud = master(raw, master_wav, float(profile.music["loudness_lufs"]),
                  float(profile.music["true_peak_db"]),
                  outro_fade_s=float(profile.music.get("outro_fade_s", 0.0)))
    mp3 = out_dir / f"{base}.mp3"
    flac = out_dir / f"{base}.flac"
    encode_flac(master_wav, flac)

    start, length = best_window(decode(master_wav), int(brief["bpm"]), float(brief["short_s"]))
    short_wav = out_dir / "short.wav"
    cut(master_wav, short_wav, start, length)
    # the Short pulses on the beat, so lock it to the beat grid of this cut
    beat_offset = beat_phase(decode(short_wav).mean(axis=1), float(brief["bpm"]))

    fam = profile.family(brief["family"])
    art = make_cover(fam, brief, profile.artist["name"], out_dir, art_mode)
    cover_named = out_dir / f"{base}-cover.jpg"
    shutil.copy(out_dir / "cover.jpg", cover_named)

    # tagged only now the cover exists: a downloaded track should show its own title,
    # artist and artwork in every player, not a filename over a blank square
    encode_mp3(master_wav, mp3, tags={
        "title": brief["title"],
        "artist": profile.artist["name"],
        "album_artist": profile.artist["name"],
        "album": profile.artist["name"],
        "date": brief["date"],
        "genre": ", ".join(x for x in (brief.get("family_name"), brief.get("lane_name")) if x),
        "TBPM": str(int(brief["bpm"])),
        "comment": f"{brief.get('key', '')} - {int(brief['bpm'])} BPM",
        "WOAR": "https://anchor.anchit-tandon.com/",
    }, cover=out_dir / "cover_600.jpg")

    mp4 = out_dir / f"{base}-short.mp4"
    video = render_short(out_dir / "cover_1080.jpg", short_wav, mp4, fam, brief,
                         profile.artist["name"], profile.artist["handle"], out_dir / "video-work",
                         beat_offset=beat_offset)
    poster_frame(mp4, out_dir / "poster.jpg", min(3.0, length / 2))

    meta = {
        "brief": brief,
        "qc": {"audio": stats_audio, "attempts": attempts_log, "warnings": attempts_log[-1]["warn"]},
        "loudness": loud,
        "engine": stats,
        "art": art,
        "short_window": {"start_s": start, "length_s": length, "beat_offset_s": beat_offset},
        "video": video,
        "files": {"base": base, "mp3": mp3.name, "flac": flac.name, "short": mp4.name,
                  "cover": cover_named.name, "cover_600": "cover_600.jpg", "poster": "poster.jpg"},
        "made_at": iso(utcnow()),
    }
    write_json(out_dir / "meta.json", meta)
    (out_dir / "release_notes.md").write_text(release_notes(profile, meta), encoding="utf-8")
    log(f"made {base}: short {video['duration']:.1f}s, {video['size_bytes'] / 1e6:.1f} MB, "
        f"master {loud['after']['input_i']} LUFS")
    return meta


def make_from_queue(profile: Profile, day: str, out_dir: Path, queued: dict, *,
                    art_mode: str | None = None, hist: list | None = None) -> dict:
    """Release a track you made yourself: master, cover, Short, notes - no generation."""
    src = Path(queued["file"])
    raw = out_dir / f"queued{src.suffix.lower()}"
    shutil.copy(src, raw)
    audio = decode(raw)
    stats_audio = analyze(audio)
    brief = make_brief(profile, day, hist or [], 0)
    brief["title"] = queued["title"]
    brief["duration_s"] = stats_audio["duration_s"]
    brief["source"], brief["source_file"] = "queue", src.name
    if queued.get("caption"):
        brief["caption"] = queued["caption"]
    est = stats_audio.get("bpm_est")
    if est:
        brief["bpm"] = int(round(est))
    heard = estimate_key(audio.mean(axis=1))
    if heard and heard[1] >= 0.25:
        brief["key"], brief["key_confidence"] = heard[0], heard[1]
    brief.update(describe(profile, brief))
    log(f"queue drop: {brief['title']!r} | {brief['lane_name']} | {brief['bpm']} BPM | "
        f"{brief['key']} | {brief['duration_s']:.0f}s from {src.name}")
    ok, fails, warns = quality_gate(stats_audio, brief)
    warn = list(warns) + ([f"kept despite: {'; '.join(fails)}"] if fails else [])
    attempts_log = [{"attempt": 0, "seed": brief["seed"], "ok": True, "fail": [], "warn": warn,
                     "source": src.name}]
    meta = finish(profile, brief, raw, stats_audio,
                  {"engine": "queue", "source_file": src.name}, attempts_log, out_dir, art_mode)
    mark_done(src, src.parent / "done")
    return meta


def release_notes(profile: Profile, meta: dict) -> str:
    b, q = meta["brief"], meta["qc"]["audio"]
    return "\n".join([
        f"## {b['title']}",
        "",
        f"**{profile.artist['name']}** · {b['lane_name']} · {b['bpm']} BPM · {b['key']}",
        "",
        f"- Genre: {b['genre_line']}",
        f"- Style: {b['style_line']}",
        f"- Visual family: {b['family_name']}",
        f"- Master loudness: {meta['loudness']['after']['input_i']} LUFS, true peak {meta['loudness']['after']['input_tp']} dBTP",
        f"- Engine: ACE-Step 1.5 ({meta['engine'].get('model', 'acestep')}) via acestep.cpp "
        f"(seed {b['seed']}), tempo estimate {q.get('bpm_est')} BPM",
        f"- Cover: {meta['art']['source']}",
        "",
        "Made with AI-assisted music tools (ACE-Step 1.5, MIT licence).",
    ]) + "\n"


# ---------------------------------------------------------------------- publish
def publish(profile: Profile, drop_dir: Path, media_url: str, *, dry_run: bool = False,
            now: bool = False, site_only: bool = False) -> dict:
    meta = read_json(drop_dir / "meta.json")
    brief = meta["brief"]
    yt = profile.youtube
    post_at = datetime.fromisoformat(brief["post_at"].replace("Z", "+00:00"))
    due = None if now else schedule_for(post_at)
    common = dict(title=brief["youtube_title"], description=brief["description"], video_url=media_url,
                  due_at=due, category_id=str(yt["category_id"]), privacy=yt["privacy"],
                  ai_generated=bool(yt["ai_generated"]), notify=bool(yt["notify_subscribers"]))
    if dry_run or site_only:
        result = {"dry_run": dry_run, "site_only": site_only,
                  "payload": build_post_input("NOT_SENT", **common),
                  "status": "dry-run" if dry_run else "released", "created_at": iso(utcnow())}
        write_json(drop_dir / "publish.json", result)
        log("publish: " + ("dry run" if dry_run else "site-only release (BUFFER_API_KEY not set)")
            + ", nothing sent to Buffer")
        return result
    try:
        media = verify_media_url(media_url, expect_min_bytes=int(meta["video"]["size_bytes"] * 0.9))
        common["video_url"] = media["url"]
        buf = Buffer(env("BUFFER_API_KEY") or "")
        ch = buf.youtube_channel(profile.artist["youtube_channel_id"], env("BUFFER_CHANNEL_ID"))
        post = buf.create_short(ch["id"], **common)
    except BufferError as exc:
        # the drop still goes out on the website; the status page shows the YouTube failure
        write_json(drop_dir / "publish.json", {"dry_run": False, "status": "error", "error": str(exc)[:500],
                                               "created_at": iso(utcnow())})
        raise
    result = {"dry_run": False, "post_id": post["id"], "status": post.get("status"), "due_at": post.get("dueAt"),
              "external_link": post.get("externalLink"), "channel": {"id": ch["id"], "name": ch.get("name")},
              "media": media, "created_at": iso(utcnow())}
    write_json(drop_dir / "publish.json", result)
    log(f"publish: Buffer post {post['id']} {post.get('status')} due {post.get('dueAt')}")
    return result


# ----------------------------------------------------------------------- record
def record(profile: Profile, drop_dir: Path, *, repo: str | None = None, short_url: str | None = None,
           run_url: str | None = None, catalog_path: Path = CATALOG_PATH, status_path: Path = STATUS_PATH,
           site_dir: Path = SITE) -> dict:
    meta = read_json(drop_dir / "meta.json")
    pub = read_json(drop_dir / "publish.json", {}) or {}
    brief, files = meta["brief"], meta["files"]
    tag = f"drop-{brief['id']}"
    covers = site_dir / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    shutil.copy(drop_dir / files["cover_600"], covers / f"{brief['id']}.jpg")
    status = "dry-run" if pub.get("dry_run") else (pub.get("status") or "made")
    if status == "buffer":   # Buffer's name for a queued post
        status = "scheduled"
    drop = {
        **{k: brief[k] for k in ("id", "date", "title", "lane", "lane_name", "bpm", "key", "family",
                                 "family_name", "duration_s", "short_s", "genre_line", "style_line",
                                 "caption", "seed")},
        "engine": {"name": meta["engine"].get("engine"), "steps": meta["engine"].get("steps"),
                   "render_s": meta["engine"].get("total_s"), "threads": meta["engine"].get("threads"),
                   "model": meta["engine"].get("model"), "guidance": meta["engine"].get("guidance"),
                   "source_file": meta["engine"].get("source_file")},
        "cover": f"covers/{brief['id']}.jpg",
        "accent": profile.family(brief["family"]).accent,
        "audio_url": f"https://github.com/{repo}/releases/download/{tag}/{files['mp3']}" if repo else None,
        "release_url": f"https://github.com/{repo}/releases/tag/{tag}" if repo else None,
        "short_url": short_url,                       # GitHub Pages copy: only the last few stay online
        # the release keeps the Short forever, so that is what the website plays
        "video_url": f"https://github.com/{repo}/releases/download/{tag}/{files['short']}" if repo else None,
        "youtube_url": pub.get("external_link"),
        "buffer_post_id": pub.get("post_id"),
        "status": status,
        "error": pub.get("error"),
        "post_at": pub.get("due_at") or brief["post_at"],
        "qc": {"bpm_est": meta["qc"]["audio"].get("bpm_est"), "lufs": meta["loudness"]["after"]["input_i"],
               "warnings": meta["qc"]["warnings"]},
        "art_source": meta["art"]["source"],
        "created_at": meta["made_at"],
    }
    cat = catalog.load(catalog_path, profile)
    catalog.upsert(cat, drop)
    catalog.save(cat, catalog_path)
    if catalog.history(cat)[0]["id"] == brief["id"]:  # newest drop becomes the social preview image
        og_card(drop_dir / "cover.jpg", brief["title"], f"{brief['lane_name']} · {brief['bpm']} BPM",
                profile.family(brief["family"]).accent, site_dir / "og.jpg", profile.artist["name"])
    next_day = (Date.fromisoformat(brief["date"]) + timedelta(days=1)).isoformat()
    catalog.update_status(
        status_path,
        last_run={"result": "ok" if status != "dry-run" else "dry-run", "stage": "done", "drop_id": brief["id"],
                  "title": brief["title"], "finished_at": iso(utcnow()), "run_url": run_url, "error": None},
        next_post_at=iso(post_time(profile, next_day)),
        streak=catalog.streak(cat),
        totals={"drops": len(cat["drops"])},
        engine=meta.get("engine"),
        schedule={"post_time_utc": profile.schedule["post_time_utc"]},
    )
    log(f"record: catalog now has {len(cat['drops'])} drop(s)")
    return drop


# ------------------------------------------------------------------------- sync
def sync(profile: Profile, *, limit: int = 7, catalog_path: Path = CATALOG_PATH) -> int:
    """Pull Buffer status (sent/error + YouTube link) for recent drops."""
    key = env("BUFFER_API_KEY")
    if not key:
        log("sync: BUFFER_API_KEY not set, skipping")
        return 0
    cat = catalog.load(catalog_path, profile)
    buf = Buffer(key)
    changed = 0
    for drop in catalog.history(cat)[:limit]:
        if not drop.get("buffer_post_id") or (drop.get("status") == "sent" and drop.get("youtube_url")):
            continue
        try:
            post = buf.post(drop["buffer_post_id"])
        except BufferError as exc:
            log(f"sync: {drop['id']} lookup failed: {exc}")
            continue
        new_status = post.get("status") or drop.get("status")
        link = post.get("externalLink") or drop.get("youtube_url")
        if new_status != drop.get("status") or link != drop.get("youtube_url"):
            drop["status"], drop["youtube_url"] = new_status, link
            if post.get("error"):
                drop["error"] = post["error"].get("message")
            catalog.upsert(cat, drop)
            changed += 1
    if changed:
        catalog.save(cat, catalog_path)
    log(f"sync: {changed} drop(s) updated")
    return changed


def fail(stage: str, error: str, run_url: str | None = None, status_path: Path = STATUS_PATH) -> None:
    catalog.update_status(status_path, last_run={"result": "failed", "stage": stage, "error": error[:600],
                                                 "finished_at": iso(utcnow()), "run_url": run_url})


def today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()
