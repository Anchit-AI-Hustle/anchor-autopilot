"""One-off videos (a lyric video, a special cut) uploaded with the channel's own credentials.

``site/data/uploads.json`` lists each video: the GitHub release that holds the file (and its
thumbnail), and the title, description and tags it goes up with. ``run`` uploads every entry
that has no ``youtube_url`` yet, sets its thumbnail, adds it to the channel playlist, and writes
the link back after each one, so a second run never uploads it twice.
"""
from __future__ import annotations

from pathlib import Path

from .config import CATALOG_PATH, Profile
from .util import iso, log, read_json, utcnow, write_json
from .versions import RELEASES, fetch
from .youtube import YouTube, playlist_id

UPLOADS_PATH = CATALOG_PATH.parent / "uploads.json"


def pending(data: dict) -> list[dict]:
    return [e for e in data.get("uploads", []) if not e.get("youtube_url")]


def run(profile: Profile, *, repo: str, work: Path, api=None, path: Path = UPLOADS_PATH) -> dict:
    data = read_json(path, {"uploads": []}) or {"uploads": []}
    todo = pending(data)
    done = {"uploaded": [], "errors": []}
    if not todo:
        log("uploads: nothing pending")
        return done
    api = api or YouTube()
    yt = profile.youtube
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
        for step, fn in steps:
            try:
                fn()
            except Exception as exc:      # noqa: BLE001 - cosmetic legs, logged
                log(f"uploads: {e['id']}: {step} failed: {exc}")
        done["uploaded"].append(f"{e['id']} -> {up['id']}")
    return done
