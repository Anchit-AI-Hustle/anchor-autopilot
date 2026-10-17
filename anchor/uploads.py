"""One-off videos (a lyric video, a special cut) uploaded with the channel's own credentials.

``site/data/uploads.json`` lists each video: the GitHub release that holds the file (and its
thumbnail), and the title, description and tags it goes up with. ``run`` uploads every entry
that has no ``youtube_url`` yet, sets its thumbnail, adds it to the channel playlist, and writes
the link back after each one, so a second run never uploads it twice.
"""
from __future__ import annotations

import re
import urllib.request
from pathlib import Path

from .config import CATALOG_PATH, Profile
from .util import iso, log, read_json, utcnow, write_json
from .versions import RELEASES, fetch
from .youtube import YouTube, playlist_id

UPLOADS_PATH = CATALOG_PATH.parent / "uploads.json"


MARK = "Motion visualizer, made for this track."   # every new motion video says so in its description
MAX_PER_RUN = 3          # 1,600 API units each; the daily drop needs two more out of the channel's 10,000


def seconds(iso_duration: str | None) -> int:
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration or "")
    return 0 if not m else int(m[1] or 0) * 3600 + int(m[2] or 0) * 60 + int(m[3] or 0)


def _on_release(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status < 400
    except Exception:                     # noqa: BLE001 - not there (yet)
        return False


def queue_motion(profile: Profile, data: dict, catalog: dict, repo: str, videos: list[dict], exists=_on_release) -> list[str]:
    """One upload entry per song whose motion video is on its release (the render leaves a
    ``-motion.json`` marker there): the new full video goes up, and the song's old full videos
    on the channel (same name, a minute or longer, not the new one) are set to private after it."""
    from . import fullvideos, motion
    from .ledger import clean_title
    have = {e["id"] for e in data.setdefault("uploads", [])}
    added = []
    for d in motion.songs(catalog):
        eid = f"motion-{d['id']}"
        if eid in have:
            continue
        base = d["audio_url"].split("?")[0].rsplit("/", 1)[-1].rsplit(".", 1)[0]
        tag = f"drop-{d['id']}"
        if not exists(RELEASES.format(repo=repo, tag=tag, file=f"{base}-motion.json")):
            continue
        title, desc, tags = fullvideos.words(profile, d, None)
        if d.get("genre"):                    # an older song keeps the genre its old video had
            from .retitle import search_line, search_title
            title = search_title(clean_title(d["title"]), d["genre"], None, profile.artist["name"])
            desc = "\n".join([search_line(d["genre"], None, profile.artist["name"]), *desc.split("\n")[1:]])
        lines = desc.split("\n")
        desc = "\n".join([lines[0], "", MARK, *lines[1:]])
        name = clean_title(d["title"]).lower()
        same = [v for v in videos if clean_title(v["title"].split(" | ")[0]).lower() == name
                and seconds(v.get("duration")) >= 60 and v.get("privacy", "public") == "public"]
        manual = [v["id"] for v in same if MARK.lower() in (v.get("description") or "").lower()]
        old = [v["id"] for v in same if v["id"] not in manual]
        entry = {"id": eid, "release": tag, "file": f"{base}-full-169.mp4",
                 "thumbnail": f"{base}-motion-frame-169.jpg", "title": title, "description": desc,
                 "tags": tags, "notify": False, "playlist": True, "replaces": old}
        if manual:                            # already uploaded by hand in YouTube Studio: never upload it twice
            entry.update(youtube_url=f"https://www.youtube.com/watch?v={manual[0]}", adopted=True)
        data["uploads"].append(entry)
        added.append(eid)
    return added


def pending(data: dict) -> list[dict]:
    return [e for e in data.get("uploads", []) if not e.get("youtube_url")]


def run(profile: Profile, *, repo: str, work: Path, api=None, path: Path = UPLOADS_PATH,
        catalog_path: Path = CATALOG_PATH, max_uploads: int = MAX_PER_RUN, exists=_on_release) -> dict:
    data = read_json(path, {"uploads": []}) or {"uploads": []}
    done = {"uploaded": [], "errors": [], "queued": [], "private": []}
    yt = profile.youtube
    try:
        api = api or YouTube()
        videos = api.channel_videos(profile.artist["youtube_channel_id"])
        done["queued"] = queue_motion(profile, data, read_json(catalog_path, {}) or {}, repo, videos, exists)
        if done["queued"]:
            write_json(path, data)
            log(f"uploads: queued motion videos {', '.join(done['queued'])}")
    except Exception as exc:              # noqa: BLE001 - the queued one-offs still go up
        log(f"uploads: motion queue skipped: {exc}")
    for e in data.get("uploads", []):     # a hand upload: its old videos go private here, cheaply
        if e.get("adopted") and not e.get("replaced") and api is not None:
            try:
                for vid in e.get("replaces") or []:
                    api.set_privacy(vid, "private")
                    done["private"].append(vid)
                e["replaced"] = True
                write_json(path, data)
            except Exception as exc:      # noqa: BLE001 - retried next run
                log(f"uploads: {e['id']}: private failed: {exc}")
    todo = pending(data)[:max_uploads]
    if not todo:
        log("uploads: nothing pending")
        return done
    api = api or YouTube()
    for e in todo:
        try:
            video = fetch(RELEASES.format(repo=repo, tag=e["release"], file=e["file"]), work / e["file"], 1_000_000)
            up = api.upload(video, title=e["title"], description=e["description"], tags=e.get("tags") or [],
                            category_id=str(yt["category_id"]), privacy="public",
                            ai_generated=bool(yt["ai_generated"]), notify=bool(e.get("notify", yt["notify_subscribers"])))
        except Exception as exc:          # noqa: BLE001 - one entry's failure never stops the rest
            log(f"uploads: {e['id']}: {exc}")
            done["errors"].append(f"{e['id']}: {str(exc)[:300]}")
            continue
        e["youtube_url"] = f"https://www.youtube.com/watch?v={up['id']}"
        e["uploaded_at"] = iso(utcnow())
        write_json(path, data)
        steps = []
        if e.get("thumbnail"):
            steps.append(("thumbnail", lambda: api.set_thumbnail(
                up["id"], fetch(RELEASES.format(repo=repo, tag=e["release"], file=e["thumbnail"]), work / e["thumbnail"], 10_000))))
        pl = playlist_id(yt.get("playlist_url"))
        if pl and e.get("playlist", True):
            steps.append(("playlist", lambda: api.add_to_playlist(up["id"], pl)))
        for vid in e.get("replaces") or []:
            steps.append((f"private {vid}", lambda vid=vid: (api.set_privacy(vid, "private"), done["private"].append(vid))))
        for step, fn in steps:
            try:
                fn()
            except Exception as exc:      # noqa: BLE001 - cosmetic legs, logged
                log(f"uploads: {e['id']}: {step} failed: {exc}")
        e["replaced"] = True
        write_json(path, data)
        done["uploaded"].append(f"{e['id']} -> {up['id']}")
    return done
