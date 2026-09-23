"""Your own Suno songs go out first, unless they are personal, off format, or another take."""
import json

from anchor import autoqueue, queue
from anchor.config import load_profile


def _songs():
    return [
        {"id": "a1", "title": "Iron Hymn", "tags": "hard techno", "rating": 7.9, "postable": True, "group": "g1", "duration_s": 200, "url": "u", "video_url": ""},
        {"id": "a2", "title": "Iron Hymn", "tags": "hard techno", "rating": 7.2, "postable": True, "group": "g1", "duration_s": 190, "url": "u", "video_url": ""},
        {"id": "b1", "title": "Happy Birthday Aashna", "tags": "hard techno", "rating": 9.9, "postable": True, "group": None, "duration_s": 150, "url": "u", "video_url": ""},
        {"id": "c1", "title": "Ballad", "tags": "for my love, slow piano", "rating": 8.0, "postable": True, "group": None, "duration_s": 150, "url": "u", "video_url": ""},
        {"id": "d1", "title": "Rap Thing", "tags": "rap", "rating": 5.0, "postable": False, "verdict": "hip hop", "group": None, "duration_s": 150, "url": "u", "video_url": ""},
        {"id": "e1", "title": "Project Mayhem Part 3", "tags": "hard techno", "rating": 8.5, "postable": True, "group": None, "duration_s": 150, "url": "u", "video_url": ""},
        {"id": "f1", "title": "Quiet Word", "tags": "hard techno", "rating": 5.5, "postable": True, "group": None, "duration_s": 150, "url": "u", "video_url": ""},
        {"id": "s1", "title": "Secret One", "tags": "hard techno", "rating": 9.0, "postable": True, "group": None, "duration_s": 150, "url": "u", "video_url": ""},
    ]


def test_plan_holds_personal_off_format_low_rated_and_sibling_takes(tmp_path):
    p = load_profile()
    p.raw["queue"]["never_titles"] = ["Secret One"]
    qdir = tmp_path / "queue"; qdir.mkdir()
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps({"drops": [{"id": "2026-09-13", "title": "Project Mayhem"}]}))
    rows = {r["id"]: r for r in autoqueue.plan(p, _songs(), qdir, cat)}
    assert rows["a1"]["verdict"] == "eligible"
    assert rows["b1"]["verdict"] == "held" and "birthday" in rows["b1"]["reason"]
    assert rows["c1"]["verdict"] == "held" and "my love" in rows["c1"]["reason"]
    assert rows["s1"]["verdict"] == "held" and "never list" in rows["s1"]["reason"]
    assert rows["d1"]["verdict"] == "held" and "not on format" in rows["d1"]["reason"]
    assert rows["f1"]["verdict"] == "held" and "floor" in rows["f1"]["reason"]
    assert rows["e1"]["verdict"] == "held" and "another take" in rows["e1"]["reason"]   # Project Mayhem is out
    # the best eligible one is queued, then nothing more while it waits
    entry = autoqueue.fill(p, _songs(), qdir, cat)
    assert entry["suno_id"] == "a1" and entry["title"] == "Iron Hymn"
    assert autoqueue.fill(p, _songs(), qdir, cat) is None
    rows = {r["id"]: r for r in autoqueue.plan(p, _songs(), qdir, cat)}
    assert rows["a1"]["verdict"] == "queued" and rows["a2"]["verdict"] == "held"   # its twin now waits behind the guard


def test_forced_entry_passes_the_same_idea_guard(tmp_path):
    from anchor.suno import queue_entry
    p = load_profile()
    qdir = tmp_path / "queue"; qdir.mkdir()
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps({"drops": [{"id": "2026-09-13", "title": "Project Mayhem"}]}))
    song = next(s for s in _songs() if s["id"] == "e1")
    queue_entry(song, qdir, force=True)
    name = next(iter(json.loads((qdir / "queue.json").read_text())))
    assert json.loads((qdir / "queue.json").read_text())[name]["force"] is True
    # without force the guard would skip it; with force it is reserved for release
    assert [n for n, _ in queue.reserved(qdir)] == [name]
    rows = {r["id"]: r for r in autoqueue.plan(p, _songs(), qdir, cat)}
    assert rows["e1"]["verdict"] == "queued"


def test_auto_can_be_switched_off(tmp_path):
    p = load_profile()
    p.raw["queue"]["auto"] = False
    qdir = tmp_path / "queue"; qdir.mkdir()
    assert autoqueue.fill(p, _songs(), qdir, tmp_path / "catalog.json") is None and not (qdir / "queue.json").exists()
