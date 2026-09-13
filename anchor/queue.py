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


def pending(queue_dir: Path = QUEUE) -> list[Path]:
    if not queue_dir.exists():
        return []
    return sorted(p for p in queue_dir.iterdir()
                  if p.is_file() and p.suffix.lower() in AUDIO and not p.name.startswith("."))


def reserved(queue_dir: Path = QUEUE) -> list[tuple[str, dict]]:
    """Queued songs that are only a reference so far — no audio on disk yet.

    The site's Add to YouTube button queues by reference, so the repo stays small; the
    audio is fetched at release time. Name order is quality order, best first.
    """
    meta = read_json(queue_dir / "queue.json", {}) or {}
    return sorted(((n, e) for n, e in meta.items()
                   if not e.get("released_at") and not (queue_dir / n).exists()),
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


def released(queue_dir: Path | None = None) -> dict[str, str]:
    """Suno id -> when it went out, for every song the queue has already released."""
    qdir = Path(queue_dir) if queue_dir else QUEUE
    meta = read_json(qdir / "queue.json", {}) or {}
    return {e["suno_id"]: e["released_at"] for e in meta.values()
            if e.get("released_at") and e.get("suno_id")}
