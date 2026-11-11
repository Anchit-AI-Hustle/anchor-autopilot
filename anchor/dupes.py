"""One song, one video: the duplicate check across the channel, the playlist and every upload.

Anchit, 2026-11-10: "ensure old songs arent reuploaded again and again - carry out a complete
duplicacy check in the videos based on the music and ensure that only unique videos and audios
are there in the playlist and in the videos uploaded too".

Two layers:

- By the music: every released master is printed (anchor/unique.py: loudness envelope and band
  sequence). Two releases that are the same record, or sound alike, are one song; the later one
  is the duplicate (``audio_pairs``, written to site/data/dupes.json by ``anchor dupes``).
- By the channel: every public upload is grouped by its song (title key, merged through the
  audio pairs and the channel's sound-alikes). Each song keeps ONE canonical full video: the one
  the catalogue records, else the replacement a lyric re-cut declared, else the first upload.
  Every other full video of the same music is a duplicate. A song also keeps one Short (the
  one the catalogue records, else the first); every other Short of it is a duplicate.

What happens with it: the ANCHOR playlist holds only the canonical full video of each unique
song (anchor/playlists.py), nothing uploads a full video of a song that already has one on the
channel unless it is a declared replacement (``is_reupload``), and ``apply`` takes every
duplicate off the channel (Anchit, 2026-11-10: "ensure duplicate ones are removed"). Taken off
means set to private: nothing is ever deleted, so any of them can be put back from Studio.
Songs that only sound alike (not the same record) stay on the channel, out of the playlist.
"""
from __future__ import annotations

from pathlib import Path

from .config import CATALOG_PATH
from .fullvideos import SHORT_MAX_S, key, seconds
from .util import read_json

DUPES_PATH = CATALOG_PATH.parent / "dupes.json"


def _vid(url: str | None) -> str | None:
    if not url:
        return None
    u = url.split("?v=")[-1] if "?v=" in url else url.rstrip("/").rsplit("/", 1)[-1]
    return u.split("&")[0] or None


def is_short(v: dict) -> bool:
    return 0 < seconds(v.get("duration")) <= SHORT_MAX_S


def audio_pairs(prints: dict[str, dict], titles: dict[str, str]) -> list[dict]:
    """Releases whose music is the same record or sounds alike, the later one first in each
    pair as the duplicate. ``prints`` maps drop id -> unique.prints(); ids sort by date."""
    from . import unique
    ids = sorted(prints)
    out = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            score = unique.similarity(prints[a], prints[b])
            same, alike = unique.is_same_record(score), unique.sounds_alike(score)
            if same or alike:
                out.append({"duplicate": b, "of": a, "duplicate_title": titles.get(b, b), "of_title": titles.get(a, a),
                            "same_record": bool(same), "score": {k: round(v, 3) for k, v in score.items()}})
    return out


def song_key(title: str) -> str:
    """A title's song, without what only names the version: '(Lyric Video)', '[Official]',
    '#shorts' (Kindness Needs Truth and its lyric video are one song, 2026-11-09)."""
    import re
    return key(re.sub(r"\([^)]*\)|\[[^\]]*\]|#\w+", " ", title))


def song_of(title: str, merge: dict[str, str]) -> str:
    """The song a title belongs to, following merges (duplicate -> original) to the end."""
    k, seen = song_key(title), set()
    while k in merge and k not in seen:
        seen.add(k)
        k = merge[k]
    return k


def renamed(catalog: dict) -> dict[str, str]:
    """Queued songs that went out under another name (drop title key -> its own Suno title key):
    Start It Tonight is Pressure Spiral, Doors Blown Open is New Beginnings (2026-11-11)."""
    from .queue import _title_from
    out = {}
    for d in (catalog or {}).get("drops", []):
        src = ((d.get("engine") or {}) if isinstance(d.get("engine"), dict) else {}).get("source_file")
        if src and d.get("title"):
            a, b = song_key(d["title"]), song_key(_title_from(src))
            if a and b and a != b:
                out[a] = b
    return out


def merges(channel: dict, dupes: dict, catalog: dict | None = None) -> dict[str, str]:
    """Songs that are one song under two names (duplicate -> original): the same record, two
    songs that sound alike, and a queued song that went out under a new name."""
    m = {}
    # only unique songs on the channel (Anchit, 2026-11-11: "ensure all correct unique songs only
    # exist - remove all duplicates"): the same record AND songs that sound alike are one song
    for p in dupes.get("audio_pairs", []):
        m.setdefault(song_key(p["duplicate_title"]), song_key(p["of_title"]))
    for a, b in ((channel or {}).get("sound_alikes") or {}).items():
        m.setdefault(song_key(a), song_key(b))
    for a, b in renamed(catalog or {}).items():
        m.setdefault(a, b)
    return m


def preferred(catalog: dict, uploads: dict) -> tuple[set[str], set[str]]:
    """(video ids the robot recorded for a song, its full video and its Short; video ids a later
    upload replaced)."""
    keep, replaced = set(), set()
    for d in catalog.get("drops", []):
        for f in ("youtube_full_url", "youtube_url", "youtube_short_url"):
            v = _vid(d.get(f))
            if v:
                keep.add(v)
    for e in uploads.get("uploads", []):
        new = _vid(e.get("youtube_url"))
        if new:
            keep.add(new)
        replaced |= set(e.get("replaces") or [])
    keep -= replaced
    return keep, replaced


def engagement(v: dict) -> int:
    """How much a video is watched and liked: views, plus likes and comments weighted up."""
    return int(v.get("view") or 0) + 20 * int(v.get("like") or 0) + 50 * int(v.get("comment") or 0)


def audit(videos: list[dict], catalog: dict, uploads: dict, channel: dict, dupes: dict) -> dict:
    """Group the channel's public videos by song: the canonical full video of each, and every
    duplicate with the reason. ``videos`` are YouTube.channel_videos() rows."""
    merge = merges(channel, dupes, catalog)
    # a song that went out again under a new name keeps its first upload, the original
    again = set(renamed(catalog).values())
    keep, replaced = preferred(catalog, uploads)
    songs: dict[str, dict] = {}
    # the Data API lists uploads newest first: without dates the later position is the older video
    age = {v["id"]: -i for i, v in enumerate(videos)}
    for v in videos:
        if v.get("privacy") != "public":
            continue
        s = songs.setdefault(song_of(v["title"], merge), {"full": [], "short": []})
        s["short" if is_short(v) else "full"].append(v)
    canonical, duplicates = {}, []
    for song, s in songs.items():
        fulls = s["full"]
        if fulls:
            # the copy people watch stays; the ones with the least engagement go private (Anchit,
            # 2026-11-11: "choose the ones with the least engagement to remove"). Ties: the
            # original over a renamed repost, then the recorded one, then the oldest
            first = song in again
            ranked = sorted(fulls, key=lambda v: (-engagement(v), v["id"] in replaced,
                                                  False if first else v["id"] not in keep,
                                                  v.get("published") or "", age[v["id"]]))
            best = ranked[0]
            canonical[song] = best
            for v in ranked[1:]:
                why = ("replaced by a newer upload of the same song" if v["id"] in replaced
                       else "same music as " + best["title"]) + f" (engagement {engagement(v)} vs {engagement(best)})"
                duplicates.append({"id": v["id"], "title": v["title"], "kind": "full", "song": song,
                                   "keep": best["id"], "why": why})
        shorts = sorted(s["short"], key=lambda v: (-engagement(v), v["id"] in replaced,
                                                    False if song in again else v["id"] not in keep,
                                                    v.get("published") or "", age[v["id"]]))
        for v in shorts[1:]:
            duplicates.append({"id": v["id"], "title": v["title"], "kind": "short", "song": song,
                               "keep": shorts[0]["id"], "why": "another Short of the same song"})
    return {"songs": len(songs), "canonical": {k: v["id"] for k, v in canonical.items()},
            "duplicates": duplicates,
            "duplicate_full": [d for d in duplicates if d["kind"] == "full"],
            "audio_pairs": dupes.get("audio_pairs", [])}


def is_reupload(title: str, videos: list[dict], channel: dict | None = None, dupes: dict | None = None,
                replaces: list[str] | tuple[str, ...] = (), catalog: dict | None = None) -> str | None:
    """The id of a public full video of the same music already on the channel (None when the
    song has none, or when that video is one this upload declares it replaces)."""
    merge = merges(channel or {}, dupes or {}, catalog)
    song = song_of(title, merge)
    for v in videos:
        if (v.get("privacy") == "public" and not is_short(v) and v["id"] not in set(replaces)
                and song_of(v["title"], merge) == song):
            return v["id"]
    return None


def load() -> dict:
    return read_json(DUPES_PATH, {}) or {}


def build_audio(catalog_path: Path, work: Path) -> dict:
    """Print every released master and pair the duplicates (the audio half of ``anchor dupes``)."""
    from . import unique
    cat = read_json(catalog_path, {}) or {}
    drops = cat.get("drops", [])
    prints = unique.released_prints(catalog_path, work, limit=len(drops) or 1)
    titles = {d["id"]: d.get("title", d["id"]) for d in drops}
    return {"printed": len(prints), "releases": len(drops), "audio_pairs": audio_pairs(prints, titles)}


def apply(api, report: dict, *, limit: int = 40) -> dict:
    """Take every duplicate off the channel: set it private (never deleted). At most ``limit``
    a run (50 quota units each); the rest go on the next run."""
    done = {"private": [], "errors": []}
    for d in report["duplicates"][:limit]:
        try:
            api.set_privacy(d["id"], "private")
            done["private"].append(f"{d['title']} ({d['id']}): {d['why']}")
            done.setdefault("moved", {})[d["id"]] = d["keep"]
        except Exception as exc:          # noqa: BLE001 - one video never stops the rest
            if "quotaExceeded" in str(exc):
                done["errors"].append("quota spent; the rest go private on the next run")
                break
            done["errors"].append(f"{d['id']}: {str(exc)[:200]}")
    return done


def repoint(catalog: dict, applied_ids: dict[str, str]) -> int:
    """The site's links follow the copy that stays: a drop whose full video or Short went private
    as a duplicate now points at the kept one. ``applied_ids`` maps private id -> kept id."""
    n = 0
    for d in catalog.get("drops", []):
        for f in ("youtube_full_url", "youtube_url", "youtube_short_url"):
            v = _vid(d.get(f))
            if v and v in applied_ids:
                d[f] = d[f].replace(v, applied_ids[v])
                n += 1
    return n
