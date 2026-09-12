"""Catalog (every drop, newest first) and run status. Both feed the website."""
from __future__ import annotations

from pathlib import Path

from .config import CATALOG_PATH, STATUS_PATH, Profile
from .util import iso, read_json, utcnow, write_json

DROP_FIELDS = ("id", "date", "title", "lane", "lane_name", "bpm", "key", "family", "family_name",
               "duration_s", "short_s", "cover", "audio_url", "release_url", "short_url",
               "youtube_url", "buffer_post_id", "status", "post_at", "qc", "art_source",
               "created_at", "genre_line", "style_line", "error", "accent")


def load(path: Path = CATALOG_PATH, profile: Profile | None = None) -> dict:
    data = read_json(path, None) or {"drops": []}
    if profile is not None:
        a = profile.artist
        data["artist"] = {k: a[k] for k in ("name", "handle", "youtube_url", "site_url", "tagline", "bio")}
    data.setdefault("drops", [])
    return data


def history(catalog: dict) -> list[dict]:
    return sorted(catalog.get("drops", []), key=lambda d: d.get("date", ""), reverse=True)


def upsert(catalog: dict, drop: dict) -> dict:
    clean = {k: drop.get(k) for k in DROP_FIELDS if k in drop}
    drops = [d for d in catalog.get("drops", []) if d.get("id") != clean["id"]]
    drops.append(clean)
    catalog["drops"] = sorted(drops, key=lambda d: d.get("date", ""), reverse=True)
    catalog["updated_at"] = iso(utcnow())
    return catalog


def save(catalog: dict, path: Path = CATALOG_PATH) -> None:
    write_json(path, catalog)


def update_status(path: Path = STATUS_PATH, **fields) -> dict:
    status = read_json(path, None) or {}
    status.update({k: v for k, v in fields.items() if v is not None})
    status["updated_at"] = iso(utcnow())
    write_json(path, status)
    return status


def streak(catalog: dict) -> int:
    """Consecutive days (ending at the newest drop) with a published or scheduled drop."""
    from datetime import date, timedelta
    days = sorted({d["date"] for d in catalog.get("drops", []) if d.get("status") in ("scheduled", "sending", "sent", "released")},
                  reverse=True)
    if not days:
        return 0
    count, cursor = 0, date.fromisoformat(days[0])
    for day in days:
        if date.fromisoformat(day) == cursor:
            count += 1
            cursor -= timedelta(days=1)
        else:
            break
    return count
