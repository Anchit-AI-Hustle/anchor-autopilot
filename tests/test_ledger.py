"""The ledger behind /ops/: one entry per drop with variants, uploads and the reason for every field."""
import json
from pathlib import Path

from anchor import catalog, ledger
from anchor.config import load_profile
from anchor.seo import description

ROOT = Path(__file__).resolve().parents[1]
META = json.load(open(ROOT / "build/e2e/meta.json"))
PROFILE = load_profile()
CATALOG = json.load(open(ROOT / "site/data/catalog.json"))
PUB = {"dry_run": False, "status": "scheduled", "post_id": "p1", "due_at": "2026-09-22T17:30:00Z",
       "youtube": {"post_id": "p1", "status": "scheduled", "due_at": "2026-09-22T17:30:00Z", "external_link": None},
       "instagram": {"error": "BUFFER_INSTAGRAM_CHANNEL_ID not set"},
       "payload": {"youtube": {"metadata": {"youtube": {"categoryId": "10", "isAiGenerated": True}}}}}
DROP = {"id": "2026-09-22", "status": "scheduled", "cover": "covers/2026-09-22.jpg",
        "release_url": "https://github.com/x/y/releases/tag/drop-2026-09-22"}


def test_entry_explains_every_published_field():
    e = ledger.build_entry(PROFILE, META, PUB, DROP)
    names = {f["field"] for f in e["fields"]}
    for must in ("title", "youtube title", "description", "tags", "category", "licence", "AI disclosure",
                 "made for kids", "language", "post time", "cover", "thumbnail 16:9", "bpm", "key", "sound lane"):
        assert must in names, must
    assert all(f["rule"] for f in e["fields"])
    assert all(f["group"] in ("record", "content", "platform", "visual") for f in e["fields"])
    key = next(f for f in e["fields"] if f["field"] == "key")
    assert "asked G minor, heard A minor" in key["evidence"]       # the audio overrode the brief, and it says so
    assert not ledger.problems({"entries": [e]})


def test_entry_lists_variants_files_and_uploads():
    e = ledger.build_entry(PROFILE, META, PUB, DROP)
    assert [v["chosen"] for v in e["variants"] if v["kind"] == "audio"] == [True]
    assert {f["role"] for f in e["files"]} >= {"master", "short 9:16", "full video 16:9", "reel 9:16", "cover", "thumbnail 16:9"}
    by = {u["target"]: u for u in e["uploads"]}
    assert by["youtube_full"]["status"] == "scheduled" and by["youtube_full"]["post_id"] == "p1"
    assert by["instagram_reel"]["status"] == "error"
    assert by["github_release"]["url"].endswith("drop-2026-09-22")


def test_cover_redraws_become_variants():
    meta = json.loads(json.dumps(META))
    meta["art"]["tries"] = [{"seed": 1, "nearest": "2026-09-12", "distance": 40.0, "ok": False},
                            {"seed": 2, "nearest": "2026-09-05", "distance": 120.0, "ok": True}]
    e = ledger.build_entry(PROFILE, meta, PUB, DROP)
    covers = [v for v in e["variants"] if v["kind"] == "cover"]
    assert [v["ok"] for v in covers] == [False, True]
    assert "too close to 2026-09-12" in covers[0]["fail"][0]


def test_suno_siblings_are_variants_with_the_released_one_chosen():
    vs = ledger.suno_variants(CATALOG, "14-project-mayhem-f5207246.m4a")
    assert len(vs) == 4 and sum(v["chosen"] for v in vs) == 1
    assert vs[0]["chosen"] and vs[0]["score"] == max(v["score"] for v in vs)
    assert ledger.suno_variants(CATALOG, None) == [] and ledger.suno_variants({}, "x.m4a") == []


def test_refresh_copies_status_and_links_from_the_catalog():
    e = ledger.build_entry(PROFILE, META, PUB, DROP)
    book = ledger.upsert({"entries": []}, e)
    cat = {"drops": [{"id": "2026-09-22", "status": "sent", "youtube_url": "https://youtu.be/abc", "instagram_url": "https://www.instagram.com/reel/x/"}]}
    assert ledger.refresh(book, cat) == 2
    by = {u["target"]: u for u in book["entries"][0]["uploads"]}
    assert by["youtube_full"]["status"] == "sent" and by["youtube_full"]["url"] == "https://youtu.be/abc"
    assert by["instagram_reel"]["url"].endswith("/x/")
    assert ledger.refresh(book, cat) == 0                         # idempotent


def test_manual_entries_are_left_alone_and_the_book_stays_sorted(tmp_path):
    e = ledger.build_entry(PROFILE, META, PUB, DROP)
    manual = {"id": "yt-abc", "date": "2026-09-30", "title": "Hand Made", "source": "manual", "uploads": [{"target": "youtube_full", "status": "live"}], "fields": [{"field": "title", "rule": "x"}]}
    book = ledger.upsert(ledger.upsert({"entries": []}, e), manual)
    assert ledger.refresh(book, {"drops": [{"id": "yt-abc", "status": "error"}]}) == 0
    ledger.save(book, tmp_path / "ledger.json")
    saved = ledger.load(tmp_path / "ledger.json")
    assert [x["id"] for x in saved["entries"]] == ["yt-abc", "2026-09-22"]
    assert not ledger.problems(saved)
    assert ledger.problems({"entries": [{"id": "a"}, {"id": "a"}]})


def test_the_committed_ledger_is_clean_and_never_prints_the_swearing_title():
    book = ledger.load(ROOT / "site/data/ledger.json")
    assert book["entries"] and not ledger.problems(book)
    assert "Fucking" not in (ROOT / "site/data/ledger.json").read_text(encoding="utf-8")
    assert ledger.clean_title("Let’s Fucking Go!") == "Let’s F*cking Go!"


def test_description_carries_the_copyright_line():
    brief = {**META["brief"]}
    for platform in ("youtube", "instagram"):
        text = description(PROFILE, brief, platform)
        assert "© 2026 ANCHOR. All rights reserved." in text.splitlines()
