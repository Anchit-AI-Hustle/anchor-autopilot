"""Playlists stay clean, with the channel's own credentials.

Every full video on the channel is in the ANCHOR playlist (the one in [youtube] playlist_url),
whichever way it went up: the robot, Metricool or Studio. No playlist holds the same song twice,
and no playlist holds a song you left out: one you took down (``withdrawn`` in
site/data/channel.json) or one that sounds like an earlier record (``sound_alikes``, song ->
the earlier record it resembles). Shorts are left where they are. Nothing is ever deleted: an
entry leaves a playlist, the video stays on the channel.
"""
from __future__ import annotations

from pathlib import Path

from .config import CATALOG_PATH, Profile
from .fullvideos import SHORT_MAX_S, key, seconds
from .util import log, read_json

CHANNEL_PATH = CATALOG_PATH.parent / "channel.json"


def left_out(channel: dict) -> set[str]:
    return {key(t) for t in [*channel.get("withdrawn", []), *channel.get("sound_alikes", {})]}


def plan(videos: list[dict], lists: dict[str, list[dict]], main: str, channel: dict) -> dict:
    """``lists`` maps playlist id -> its entries in order ({"item", "video"}). Returns the
    entries to take out (with why) and the videos to add to ``main``, oldest first."""
    by_id = {v["id"]: v for v in videos}
    skip = left_out(channel)
    full = lambda v: v.get("privacy") == "public" and seconds(v.get("duration")) > SHORT_MAX_S
    remove, keys_in_main = [], set()
    for pl, entries in lists.items():
        seen: set[str] = set()
        for e in entries:
            v = by_id.get(e["video"])
            if not v or seconds(v.get("duration")) <= SHORT_MAX_S:
                continue                      # a Short, or a video these credentials cannot see: left alone
            k = key(v["title"])
            if k in skip:
                remove.append({"playlist": pl, "item": e["item"], "title": v["title"], "why": "left out"})
            elif k in seen:
                remove.append({"playlist": pl, "item": e["item"], "title": v["title"], "why": "same song twice"})
            else:
                seen.add(k)
        if pl == main:
            keys_in_main = seen
    add = []
    for v in reversed(videos):                # the uploads list is newest first
        k = key(v["title"])
        if full(v) and k not in skip and k not in keys_in_main:
            add.append(v)
            keys_in_main.add(k)
    return {"remove": remove, "add": add}


def run(profile: Profile, *, api=None, channel_path: Path = CHANNEL_PATH, dry_run: bool = False) -> dict:
    from .youtube import YouTube, playlist_id
    api = api or YouTube()
    main = playlist_id(profile.youtube.get("playlist_url"))
    if not main:
        raise ValueError("no [youtube] playlist_url in the profile")
    channel = read_json(channel_path, {}) or {}
    cid = profile.artist["youtube_channel_id"]
    videos = api.channel_videos(cid)
    ids = list(dict.fromkeys([main, *(p["id"] for p in api.playlists(cid))]))
    lists = {pl: api.playlist_items(pl) for pl in ids}
    p = plan(videos, lists, main, channel)
    done = {"removed": [f"{r['title']} ({r['why']}) from {r['playlist']}" for r in p["remove"]],
            "added": [v["title"] for v in p["add"]], "errors": []}
    if dry_run:
        return done
    for r in p["remove"]:
        try:
            api.remove_from_playlist(r["item"])
        except Exception as exc:          # noqa: BLE001 - one entry never stops the rest
            done["errors"].append(f"remove {r['title']}: {str(exc)[:200]}")
    for v in p["add"]:
        try:
            api.add_to_playlist(v["id"], main)
        except Exception as exc:          # noqa: BLE001
            done["errors"].append(f"add {v['title']}: {str(exc)[:200]}")
    log(f"playlists: {len(p['remove'])} entries out, {len(p['add'])} videos into the ANCHOR playlist")
    return done
