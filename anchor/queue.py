"""A queue of finished tracks to release instead of generating one.

Drop audio files into ``queue/`` and the daily robot releases the oldest one: it still
masters, cuts the Short, draws the cover, renders the video, publishes and records it.
The generator only runs when the queue is empty, so your own tracks always win.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .config import ROOT
from .util import log, read_json

QUEUE = ROOT / "queue"
DONE = QUEUE / "done"
AUDIO = (".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus")


def _title_from(name: str) -> str:
    stem = re.sub(r"^\d{1,3}[-_. ]+", "", Path(name).stem)          # strip a leading order number
    stem = re.sub(r"[-_]+", " ", stem).strip()
    stem = re.sub(r"\s*\(\s*\d+\s*\)$", "", stem)                   # "Track (2)" -> "Track"
    stem = re.sub(r"\s+[0-9a-f]{8}$", "", stem, flags=re.I)           # drop a trailing source id
    return " ".join(w if w.isupper() else w.capitalize() for w in stem.split())


def _already_posted(name: str, title: str | None, queue_dir: Path) -> bool:
    """Has this track, or another take of the same song, already gone out?

    Two guards, because they fail differently. The name guard stops the exact file coming
    back when its released_at stamp went missing. The idea guard stops the channel posting
    "Project Mayhem Part 2" the day after "Project Mayhem" - a different file, the same song,
    and the one thing a once-a-day channel cannot get away with.
    """
    from .suno import title_key
    if name in spent(queue_dir):
        return True
    key = title_key(title or _title_from(name))
    return bool(key) and key in posted_ideas()


def pending(queue_dir: Path = QUEUE, skip_spent: bool = True) -> list[Path]:
    if not queue_dir.exists():
        return []
    files = sorted(p for p in queue_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in AUDIO and not p.name.startswith("."))
    if not skip_spent:
        return files
    meta = read_json(queue_dir / "queue.json", {}) or {}
    return [p for p in files
            if not _already_posted(p.name, (meta.get(p.name) or {}).get("title"), queue_dir)]


def reserved(queue_dir: Path = QUEUE) -> list[tuple[str, dict]]:
    """Queued songs that are only a reference so far — no audio on disk yet.

    The site's Add to YouTube button queues by reference, so the repo stays small; the
    audio is fetched at release time. Name order is quality order, best first.
    """
    meta = read_json(queue_dir / "queue.json", {}) or {}
    return sorted(((n, e) for n, e in meta.items()
                   if not e.get("released_at") and not (queue_dir / n).exists()
                   and not _already_posted(n, e.get("title"), queue_dir)),
                  key=lambda ne: ne[0])


def next_track(queue_dir: Path = QUEUE) -> dict | None:
    """The next queued track with its metadata, or None when the queue is empty.

    A reference queued from the catalogue is fetched now, so a song the site says is
    next really is the one that goes out.
    """
    files = pending(queue_dir)
    if not files:
        waiting = reserved(queue_dir)
        if not waiting:
            return None
        from . import suno
        name, entry = waiting[0]
        try:
            suno.materialise(name, entry, queue_dir)
        except Exception as exc:                       # a dead link must not stall the robot
            log(f"queue: could not fetch {name}: {exc}")
            if len(waiting) == 1:
                return None
            for name, entry in waiting[1:]:
                try:
                    suno.materialise(name, entry, queue_dir)
                    break
                except Exception as exc2:
                    log(f"queue: could not fetch {name}: {exc2}")
            else:
                return None
        files = pending(queue_dir)
        if not files:
            return None
    path = files[0]
    meta = read_json(queue_dir / "queue.json", {}) or {}
    entry = dict(meta.get(path.name) or {})
    entry.setdefault("title", _title_from(path.name))
    entry["file"] = path
    log(f"queue: releasing {path.name} as {entry['title']!r} "
        f"({len(files) + len(reserved(queue_dir))} in the queue)")
    return entry


def mark_done(path: Path, done_dir: Path = DONE) -> Path:
    """Move a released track out of the queue so it is never posted twice.

    A track queued by reference has no file to move once released, so the manifest entry
    is stamped too - otherwise the next run would fetch and release it all over again.
    """
    index = path.parent / "queue.json"
    if index.exists():
        meta = read_json(index, {}) or {}
        if path.name in meta:
            from datetime import datetime, timezone
            meta[path.name]["released_at"] = (datetime.now(timezone.utc)
                                              .isoformat(timespec="seconds").replace("+00:00", "Z"))
            index.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    done_dir.mkdir(parents=True, exist_ok=True)
    target = done_dir / path.name
    n = 2
    while target.exists():
        target = done_dir / f"{path.stem}-{n}{path.suffix}"
        n += 1
    shutil.move(str(path), target)
    return target


def write_meta(queue_dir: Path, data: dict) -> None:
    (queue_dir / "queue.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def line_up(queue_dir: Path | None = None) -> list[dict]:
    """The queue as an ordered line: position 1 is the song the next daily run releases.

    Files dropped in by hand come first because the pipeline releases those before it
    fetches any reference; within each group, name order is quality order.
    """
    qdir = Path(queue_dir) if queue_dir else QUEUE
    meta = read_json(qdir / "queue.json", {}) or {}
    line, pos = [], 0
    for name, have_audio in ([(p.name, True) for p in pending(qdir)]
                             + [(n, False) for n, _ in reserved(qdir)]):
        entry = meta.get(name, {})
        pos += 1
        line.append({
            "name": name,
            "position": pos,
            "title": entry.get("title") or _title_from(name),
            "suno_id": entry.get("suno_id"),
            "rating": entry.get("rating"),
            "queued_at": entry.get("queued_at"),
            "have_audio": have_audio,
        })
    return line


def _drops(catalog_path: Path | None = None) -> list[dict]:
    from .config import CATALOG_PATH
    cat = read_json(Path(catalog_path) if catalog_path else CATALOG_PATH, {}) or {}
    return cat.get("drops") or []


def spent(queue_dir: Path | None = None, catalog_path: Path | None = None) -> set[str]:
    """Queue file names that have already gone out, from both records that know.

    The stamp in queue.json is written by the runner that renders, and that runner is not
    the one that commits, so the stamp can be lost. The website's own drop list is committed
    by definition: if a track is on the site, it has been released, stamp or no stamp.
    """
    qdir = Path(queue_dir) if queue_dir else QUEUE
    meta = read_json(qdir / "queue.json", {}) or {}
    names = {n for n, e in meta.items() if e.get("released_at")}
    for d in _drops(catalog_path):
        src = ((d.get("engine") or {}) if isinstance(d.get("engine"), dict) else {}).get("source_file")
        if src:
            names.add(src)
    return names


def posted_ideas(catalog_path: Path | None = None) -> set[frozenset[str]]:
    """The title-key of every song already on the website.

    Suno hands back two takes of one prompt, so "Project Mayhem" and "Project Mayhem Part 2"
    are the same song twice. Releasing the second one a day after the first is the channel
    repeating itself, which is the one thing a daily robot must not do.
    """
    from .suno import title_key
    return {title_key(d["title"]) for d in _drops(catalog_path) if d.get("title")}


def released(queue_dir: Path | None = None) -> dict[str, str]:
    """Suno id -> when it went out, for every song the queue has already released."""
    qdir = Path(queue_dir) if queue_dir else QUEUE
    meta = read_json(qdir / "queue.json", {}) or {}
    out = {e["suno_id"]: e["released_at"] for e in meta.values()
           if e.get("released_at") and e.get("suno_id")}
    spent_names = spent(qdir)
    for name in spent_names:                      # a lost stamp still counts as released
        e = meta.get(name) or {}
        if e.get("suno_id") and e["suno_id"] not in out:
            out[e["suno_id"]] = e.get("released_at") or "released"
    return out
