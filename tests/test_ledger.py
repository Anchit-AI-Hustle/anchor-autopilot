"""The ledger behind /ops/: one entry per drop with variants, uploads and the reason for every field."""
import json
from pathlib import Path

from anchor import catalog, ledger
from anchor.config import load_profile
from anchor.seo import description

ROOT = Path(__file__).resolve().parents[1]
META = json.load(open(ROOT / "tests/fixtures/drop-meta.json"))   # a real drop's meta.json, from an end-to-end run
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
        assert "© 2026 ANCHOR" in text.splitlines()


# ------------------------------------------------------------------ the words
def test_arc_finds_the_breakdown_and_the_drop():
    import numpy as np
    from anchor.audio import arc
    sr = 48_000
    t = np.arange(sr * 60) / sr
    loud = 0.5 * np.sign(np.sin(2 * np.pi * 50 * t))          # a square wave: loud
    x = loud.copy()
    x[sr * 20: sr * 30] *= 0.1                                  # 10 s breakdown at 0:20
    a = arc(np.stack([x, x], axis=1), sr)
    assert a["duration_s"] == 60.0
    assert len(a["breakdowns"]) == 1 and abs(a["breakdowns"][0]["start"] - 20) <= 2 and abs(a["breakdowns"][0]["end"] - 30) <= 2
    assert any(abs(d["at"] - 30) <= 2 for d in a["drops"]), "the return is a drop"


def test_template_copy_is_vibe_only_and_repeatable(monkeypatch):
    from anchor import copy as C
    brief = {**META["brief"], "date": "2026-09-22"}
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    a = C.write(PROFILE, brief)
    b = C.write(PROFILE, brief, {"drops": [{"at": 34.0}]})
    assert a == b and a["source"] == "template"
    assert not C.BANNED.search(a["body"]) and len(a["body"]) < 400 and a["body"].endswith(".")
    assert a["hashtags"].startswith("#") and len(a["hashtags"].split()) == 3


def test_gemini_copy_is_checked_for_clock_times_and_hype_words(monkeypatch):
    from anchor import copy as C
    brief = {**META["brief"], "date": "2026-09-22"}
    good = {"body": "Warehouse pressure with no off switch. It starts before you're ready and it does not let go.", "hashtags": "#rawstyle #hardtechno #techno"}
    bad_time = {**good, "body": "At 1:10 it explodes."}
    bad_word = {**good, "body": "Immerse yourself in the journey."}
    answers = iter([json.dumps(bad_time), json.dumps(bad_word), json.dumps(good)])
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setattr(C, "ask_gemini", lambda prompt, key: next(answers))
    out = C.write(PROFILE, brief)
    assert out["source"] == "gemini" and out["body"] == good["body"]
    # every answer bad -> the template, never a broken description
    monkeypatch.setattr(C, "ask_gemini", lambda prompt, key: json.dumps(bad_time))
    assert C.write(PROFILE, brief)["source"] == "template"


def test_description_is_the_copy_then_the_practical_block():
    brief = {**META["brief"], "copy": {"body": "Hook line. Bigger line. Biggest line.", "hashtags": "#a #b #c", "source": "template"}}
    d = description(PROFILE, brief)
    lines = d.splitlines()
    assert lines[0] == "Hook line. Bigger line. Biggest line." and d.endswith("#a #b #c") and len(d) < 500
    assert "Rawstyle Hybrid · 152 BPM · ANCHOR" in lines and any(l.endswith("· IG @anchor_at2803") for l in lines)
    ig = description(PROFILE, brief, "instagram")
    assert ig.startswith("Hook line.") and "playlist" not in ig and "#anchortechno" in ig
