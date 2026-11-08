"""Sync with Suno page (Anchit, 2026-11-09): the checklist's request is parsed, queued with its
choices, and those choices reach the post and the video. No network: Suno is faked."""
import json
from datetime import datetime, timedelta, timezone

from anchor import queue, sunopost
from anchor.brief import apply_overrides, describe
from anchor.config import load_profile

P = load_profile()


def body(songs, release="now"):
    return ("Post to YouTube from the Sync with Suno page:\n\n- X\n\n```json\n"
            + json.dumps({"form": sunopost.FORM_MARK, "release": release, "songs": songs}) + "\n```\n")


def test_the_request_is_read_from_the_issue_body():
    picks = sunopost.parse_form(body([
        {"id": "0287e07b-4e22-4d9b-9d33-78e55743e3e7", "style": "cinematic", "youtube_title": "My Title",
         "hashtags": "#a #b", "force": True},
        {"id": "e7f16cd4-0000-0000-0000-000000000000", "style": "weird"},
        {"style": "motion"}]))
    assert [p["style"] for p in picks] == ["cinematic", "motion"]          # an unknown style is motion
    assert picks[0]["youtube_title"] == "My Title" and picks[0]["force"] and not picks[1]["force"]
    assert sunopost.parse_form("no block here") == []
    assert sunopost.parse_form('```json\n{"form": "other", "songs": [{"id": "x"}]}\n```') == []


def test_the_page_starts_from_what_the_robot_would_post():
    song = {"title": "Project Mayhem Part 2", "tags": "hard techno, rawstyle hybrid, industrial, 156-158 bpm"}
    d = sunopost.defaults(P, song)
    assert d["lane"] == "rawbounce" and d["bpm"] == 156                  # word match, not "hard tech" in "hard techno"
    assert d["youtube_title"].startswith("Project Mayhem Part 2") and "ANCHOR" in d["youtube_title"]
    assert d["hashtags"].startswith("#") and d["description"].rstrip().endswith(d["hashtags"])
    assert d["style"] == "motion"
    psy = sunopost.defaults(P, {"title": "Fern", "tags": "psychedelic techno, hard techno, 165 bpm"})
    assert P.lane(psy["lane"]).group == "psy"


def test_typed_fields_win_and_hashtags_replace_the_last_line_everywhere():
    brief = {"title": "Fern", "lane": "psy", "bpm": 165, "date": "2026-11-09"}
    base = describe(P, brief)
    out = apply_overrides(dict(base), {"youtube_title": "Fern (Official) | ANCHOR", "hashtags": "psytrance, #techno"})
    assert out["youtube_title"] == "Fern (Official) | ANCHOR"
    assert out["description"].endswith("\n#psytrance #techno") and "#hardtechno" not in out["description"].splitlines()[-1]
    assert out["caption_instagram"].endswith("#psytrance #techno")
    assert out["description_short"].splitlines()[-1] == "#psytrance #techno #shorts"
    own = apply_overrides(dict(base), {"description": "My own words.\n#x"})
    assert own["description"] == "My own words.\n#x"
    assert apply_overrides(dict(base), {}) == base
    brief["overrides"] = {"youtube_title": "T"}
    assert describe(P, brief)["youtube_title"] == "T"                    # describe() re-runs keep it


def test_ticked_songs_are_queued_with_every_choice(tmp_path, monkeypatch):
    from anchor import suno
    songs = {
        "0287e07b-4e22-4d9b-9d33-78e55743e3e7": {"id": "0287e07b-4e22-4d9b-9d33-78e55743e3e7", "title": "Mayhem Two",
                                                 "tags": "hard techno", "url": "u", "rating": 8.3, "duration_s": 177,
                                                 "lyrics": "[Hook]\nWe are at war\n"},
        "e7f16cd4-1111-2222-3333-444444444444": {"id": "e7f16cd4-1111-2222-3333-444444444444", "title": "Old One",
                                                 "tags": "techno", "url": "u", "rating": 7, "duration_s": 150,
                                                 "released_at": "2026-10-01"},
    }
    monkeypatch.setattr(suno, "find", lambda handle, sid: songs[sid])
    picks = sunopost.parse_form(body([
        {"id": "0287e07b-4e22-4d9b-9d33-78e55743e3e7", "style": "cinematic", "title": "Mayhem II",
         "description": "Mine.", "hashtags": "#a", "lane": "rawbounce"},
        {"id": "e7f16cd4-1111-2222-3333-444444444444", "style": "motion"}]))
    done = sunopost.queue_selection(P, "anchor_at", picks, tmp_path)
    assert [d.get("skipped") for d in done] == [None, "already released"]
    meta = json.loads((tmp_path / "queue.json").read_text())
    ((_name, e),) = meta.items()
    assert e["title"] == "Mayhem II" and e["keep_title"] and e["style"] == "cinematic" and e["lane"] == "rawbounce"
    assert e["overrides"] == {"description": "Mine.", "hashtags": "#a"} and e["lyrics"].startswith("[Hook]")
    assert e["suno_id"] == "0287e07b-4e22-4d9b-9d33-78e55743e3e7" and e["from"] == "sync-with-suno"


def test_a_cinematic_song_waits_for_its_shots_then_goes_out_anyway(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CINEMATIC_DIR", str(tmp_path / "clips"))
    now = datetime.now(timezone.utc)
    e = {"style": "cinematic", "suno_id": "abc", "queued_at": now.isoformat()}
    assert queue.waiting_for_shots(e)
    assert not queue.waiting_for_shots({**e, "queued_at": (now - timedelta(hours=40)).isoformat()})
    assert not queue.waiting_for_shots({**e, "style": "motion"})
    d = tmp_path / "clips" / "abc"
    d.mkdir(parents=True)
    for n in range(1, 7):
        (d / f"shot-{n:02d}.mp4").write_bytes(b"x" * 20_000)
    assert not queue.waiting_for_shots(e)
    # a held entry is not offered to the run, the next one is
    q = tmp_path / "q"
    q.mkdir()
    (q / "queue.json").write_text(json.dumps({
        "10-a.m4a": {"title": "A", "style": "cinematic", "suno_id": "zzz", "queued_at": now.isoformat()},
        "20-b.m4a": {"title": "B", "style": "motion", "suno_id": "yyy", "queued_at": now.isoformat()}}))
    assert [n for n, _ in queue.reserved(q)] == ["20-b.m4a"]


def test_the_chosen_look_decides_the_video(monkeypatch):
    from anchor import cinematic, video
    asked = []
    monkeypatch.setattr(cinematic, "shots_for", lambda sid: asked.append(sid) or ["s"])
    brief = {"theme": "queue", "cinematic_id": "suno-1", "video_style": "cinematic"}
    assert video.cinematic_shots(brief) == ["s"] and asked == ["suno-1"]
    assert video.cinematic_shots({**brief, "video_style": "motion"}) == [] and asked == ["suno-1"]
    assert video.cinematic_shots({"theme": "songbook-song"}) == ["s"] and asked[-1] == "songbook-song"
