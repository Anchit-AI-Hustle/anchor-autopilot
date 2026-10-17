"""One-off videos (a lyric video, a special cut) uploaded with the channel's own credentials.

``site/data/uploads.json`` lists each video: the GitHub release that holds the file (and its
thumbnail), and the title, description and tags it goes up with. ``run`` uploads every entry
that has no ``youtube_url`` yet, sets its thumbnail, adds it to the channel playlist, and writes
the link back after each one, so a second run never uploads it twice.
"""
from __future__ import annotations

import json
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


def _held() -> dict:
    from . import motion
    return (read_json(motion.LEGACY_PATH, {}) or {}).get("hold", {}) or {}


def _vid(url: str | None) -> str:
    return (url or "").rsplit("=", 1)[-1].rsplit("/", 1)[-1]


def superseded(data: dict) -> set[str]:
    """Videos this robot uploaded that were later found wanting (the first motion uploads had no
    lyrics): they are re-done, and the old one goes private like any other old full video."""
    return {_vid(s.get("youtube_url")) for s in data.get("superseded", []) if s.get("youtube_url")}


def _key(title: str) -> str:
    """A song's name for matching videos: letters and digits only, so "Let’s F*cking Go!" and
    "Let's F*cking Go" are the same song."""
    from .ledger import clean_title
    return re.sub(r"[^a-z0-9]+", "", clean_title(title.split(" | ")[0]).lower())


def _same(videos: list[dict], title: str) -> list[dict]:
    name = _key(title)
    return [v for v in videos if _key(v["title"]) == name
            and seconds(v.get("duration")) >= 60 and v.get("privacy", "public") == "public"]


def _hand(videos: list[dict], data: dict) -> list[str]:
    """Hand uploads in YouTube Studio: the motion line in the description, not one of ours."""
    ours = superseded(data) | {_vid(e.get("youtube_url")) for e in data.get("uploads", []) if e.get("youtube_url")}
    return [v["id"] for v in videos if MARK.lower() in (v.get("description") or "").lower() and v["id"] not in ours]


def adopt_late(data: dict, videos: list[dict]) -> list[str]:
    """A song already queued for the robot that Anchit then uploaded by hand in Studio is adopted,
    never uploaded a second time."""
    adopted = []
    for e in pending(data):
        if not e["id"].startswith("motion-"):
            continue
        same = _same(videos, e["title"])
        hand = _hand(same, data)
        if hand:
            e.update(youtube_url=f"https://www.youtube.com/watch?v={hand[0]}", adopted=True,
                     replaces=[v["id"] for v in same if v["id"] not in hand])
            adopted.append(e["id"])
    return adopted


def queue_motion(profile: Profile, data: dict, catalog: dict, repo: str, videos: list[dict], exists=_on_release) -> list[str]:
    """One upload entry per song whose motion video is on its release (the render leaves a
    ``-motion.json`` marker there): the new full video goes up, and the song's old full videos
    on the channel (same name, a minute or longer, not the new one) are set to private after it."""
    from . import fullvideos, motion
    from .ledger import clean_title
    have = {e["id"] for e in data.setdefault("uploads", [])}
    hold = _held()                        # songs Anchit took down or held: never re-post
    added = []
    for d in motion.songs(catalog):
        eid = f"motion-{d['id']}"
        if eid in have or d["id"] in hold:
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
        same = _same(videos, clean_title(d["title"]))
        manual = _hand(same, data)
        old = [v["id"] for v in same if v["id"] not in manual]
        entry = {"id": eid, "release": tag, "file": f"{base}-full-169.mp4",
                 "thumbnail": f"{base}-motion-frame-169.jpg", "title": title, "description": desc,
                 "tags": tags, "notify": False, "playlist": True, "replaces": old}
        if manual:                            # already uploaded by hand in YouTube Studio: never upload it twice
            entry.update(youtube_url=f"https://www.youtube.com/watch?v={manual[0]}", adopted=True)
        data["uploads"].append(entry)
        added.append(eid)
    return added


def _marker(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:                     # noqa: BLE001 - not there (yet)
        return {}


def ready(e: dict, repo: str, read=_marker) -> bool:
    """A motion video goes up only once its release holds the current render (``motion.RENDER``):
    an older render queued earlier waits for the re-render instead of going out."""
    if not e["id"].startswith("motion-"):
        return True
    from . import motion
    mk = read(RELEASES.format(repo=repo, tag=e["release"], file=e["file"].replace("-full-169.mp4", "-motion.json")))
    return int(mk.get("render") or 1) >= motion.RENDER


def pending(data: dict, hold: dict | None = None) -> list[dict]:
    """Entries still to go up. A held song never goes up, even if it was queued before the hold."""
    hold = _held() if hold is None else hold
    return [e for e in data.get("uploads", []) if not e.get("youtube_url")
            and not (e["id"].startswith("motion-") and e["id"][len("motion-"):] in hold)]


def run(profile: Profile, *, repo: str, work: Path, api=None, path: Path = UPLOADS_PATH,
        catalog_path: Path = CATALOG_PATH, max_uploads: int = MAX_PER_RUN, exists=_on_release, read=_marker) -> dict:
    data = read_json(path, {"uploads": []}) or {"uploads": []}
    done = {"uploaded": [], "errors": [], "queued": [], "adopted": [], "private": []}
    yt = profile.youtube
    videos: list[dict] = []
    try:
        api = api or YouTube()
        videos = api.channel_videos(profile.artist["youtube_channel_id"])
        done["queued"] = queue_motion(profile, data, read_json(catalog_path, {}) or {}, repo, videos, exists)
        done["adopted"] = adopt_late(data, videos)
        if done["queued"] or done["adopted"]:
            write_json(path, data)
            log(f"uploads: queued {', '.join(done['queued']) or 'none'}; adopted from Studio {', '.join(done['adopted']) or 'none'}")
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
    waiting = [e["id"] for e in pending(data) if not ready(e, repo, read)]
    if waiting:
        log(f"uploads: waiting for the current motion render: {', '.join(waiting)}")
    todo = [e for e in pending(data) if e["id"] not in waiting][:max_uploads]
    if not todo:
        log("uploads: nothing pending")
        return done
    api = api or YouTube()
    for e in todo:                        # the song's full videos on the channel right now all go private after it
        if e["id"].startswith("motion-") and videos:
            e["replaces"] = list(dict.fromkeys([*(e.get("replaces") or []), *(v["id"] for v in _same(videos, e["title"]))]))
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
