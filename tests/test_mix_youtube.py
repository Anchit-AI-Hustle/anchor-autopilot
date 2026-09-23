"""The weekly mix and the YouTube Data API road: built from synthetic tracks, uploaded to a
fake Google. Nothing here touches the network."""
import json
from pathlib import Path

import numpy as np
import pytest

from anchor import mix, pipeline, youtube
from anchor.brief import make_brief
from anchor.config import load_profile
from anchor.music import synth_techno, write_wav


# ------------------------------------------------------------------- youtube api
class FakeGoogle:
    """Answers the five calls the uploader makes, in order, and records them."""

    def __init__(self):
        self.calls = []
        self.n = 0

    def __call__(self, method, url, *, data=None, headers=None, timeout=120):
        self.calls.append((method, url.split("?")[0], headers or {}, data))
        if url.startswith(youtube.TOKEN_URL):
            return 200, {}, json.dumps({"access_token": "at-1"}).encode()
        if "/upload/youtube/v3/videos" in url and method == "POST":
            return 200, {"Location": "https://upload.example/session-1"}, b""
        if url.startswith("https://upload.example/session-"):
            self.n += 1
            return 200, {}, json.dumps({"id": f"vid{self.n}"}).encode()
        if "/thumbnails/set" in url:
            return 200, {}, b"{}"
        if "/playlistItems" in url:
            return 200, {}, b'{"id":"pli"}'
        if "/videos" in url and method == "GET":
            return 200, {}, json.dumps({"items": [{"status": {"privacyStatus": "public", "publishAt": None}, "statistics": {"viewCount": "7"}}]}).encode()
        raise AssertionError(f"unexpected call {method} {url}")


def test_upload_is_one_resumable_session_with_the_metadata_youtube_needs(monkeypatch, tmp_path):
    g = FakeGoogle()
    monkeypatch.setattr(youtube, "_http", g)
    api = youtube.YouTube("cid", "csec", "rt")
    f = tmp_path / "v.mp4"
    f.write_bytes(b"\x00" * 1000)
    from datetime import datetime, timezone
    when = datetime(2026, 9, 27, 17, 30, tzinfo=timezone.utc)
    r = api.upload(f, title="T | Industrial Hard Techno 154 BPM | ANCHOR", description="d", tags=["a", "b"], publish_at=when)
    assert r == {"id": "vid1", "url": "https://youtu.be/vid1", "status": "scheduled", "publish_at": "2026-09-27T17:30:00Z"}
    start = next(c for c in g.calls if c[0] == "POST" and c[1].endswith("/videos"))
    body = json.loads(start[3])
    assert body["snippet"]["tags"] == ["a", "b"] and body["snippet"]["categoryId"] == "10"
    assert body["status"] == {"selfDeclaredMadeForKids": False, "containsSyntheticMedia": True, "license": "youtube",
                              "embeddable": True, "privacyStatus": "private", "publishAt": "2026-09-27T17:30:00Z"}
    assert start[2]["X-Upload-Content-Length"] == "1000" and start[2]["Authorization"] == "Bearer at-1"
    put = next(c for c in g.calls if c[0] == "PUT")
    assert put[1] == "https://upload.example/session-1" and len(put[3]) == 1000
    api.set_thumbnail("vid1", f)
    api.add_to_playlist("vid1", "PL1")
    assert g.calls[-1][1].endswith("/playlistItems") and json.loads(g.calls[-1][3])["snippet"]["playlistId"] == "PL1"
    assert api.video_status("vid1") == {"status": "sent", "publish_at": None, "views": 7}
    assert youtube.playlist_id("https://www.youtube.com/playlist?list=PLSA3gW62zSYE") == "PLSA3gW62zSYE"


def test_publish_takes_the_api_road_when_the_channel_credentials_are_set(monkeypatch, tmp_path):
    """Full track first, then the Short linking it by id; tags, thumbnail and playlist along the way."""
    g = FakeGoogle()
    monkeypatch.setattr(youtube, "_http", g)
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        monkeypatch.setenv(k, "x")
    monkeypatch.delenv("BUFFER_API_KEY", raising=False)
    p = load_profile()
    b = make_brief(p, "2026-09-27", [])
    for name in ("a-full-169.mp4", "a-short.mp4", "frame-169.jpg"):
        (tmp_path / name).write_bytes(b"\x00" * 10)
    meta = {"brief": b, "full": {"full_169": {"size_bytes": 10}, "full_916": {"size_bytes": 10}}, "video": {"size_bytes": 10},
            "files": {"full_169": "a-full-169.mp4", "short": "a-short.mp4", "thumbnail": "frame-169.jpg"}}
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    res = pipeline.publish(p, tmp_path, "https://host/a-full-169.mp4", short_url="https://host/a-short.mp4",
                           reel_url="https://host/reel.mp4")
    assert res["youtube"]["post_id"] == "vid1" and res["youtube"]["via"] == "youtube_api"
    assert res["youtube_short"]["post_id"] == "vid2" and res["error"] is None
    assert res["instagram"] == {"status": "not connected", "error": None}
    uploads = [json.loads(c[3]) for c in g.calls if c[0] == "POST" and c[1].endswith("/videos")]
    assert uploads[0]["snippet"]["title"] == b["youtube_title"] == uploads[1]["snippet"]["title"]
    assert "Full track: https://youtu.be/vid1" in uploads[1]["snippet"]["description"]
    assert "shorts" in uploads[1]["snippet"]["tags"] and b["tags"][0] in uploads[0]["snippet"]["tags"]
    assert any(c[1].endswith("/thumbnails/set") for c in g.calls) and any(c[1].endswith("/playlistItems") for c in g.calls)
    pub = json.loads((tmp_path / "publish.json").read_text())
    assert pub["youtube"]["external_link"] == "https://youtu.be/vid1"


def test_sync_asks_youtube_itself_for_api_posts(monkeypatch, tmp_path):
    g = FakeGoogle()
    monkeypatch.setattr(youtube, "_http", g)
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        monkeypatch.setenv(k, "x")
    monkeypatch.delenv("BUFFER_API_KEY", raising=False)
    p = load_profile()
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps({"drops": [{"id": "2026-09-27", "date": "2026-09-27", "title": "T", "buffer_post_id": "vid1",
                                          "youtube_via": "youtube_api", "status": "scheduled"}]}))
    assert pipeline.sync(p, catalog_path=cat, ledger_path=tmp_path / "ledger.json") == 1
    d = json.loads(cat.read_text())["drops"][0]
    assert d["status"] == "sent" and d["youtube_url"] == "https://youtu.be/vid1"


# ------------------------------------------------------------------------- mix
def _track(tmp_path, name, bpm, seconds=20, seed=1):
    f = tmp_path / f"{name}.wav"
    write_wav(f, synth_techno(seconds, bpm, seed))
    return f


def test_join_orders_by_tempo_crossfades_and_names_the_chapters(tmp_path):
    tracks = [{"id": "b", "title": "Slow One", "bpm": 130, "lane": "industrial", "file": _track(tmp_path, "b", 130, seed=2)},
              {"id": "a", "title": "Fast One", "bpm": 155, "lane": "acid", "file": _track(tmp_path, "a", 155, seed=3)},
              {"id": "c", "title": "Let’s Fucking Go!", "bpm": 150, "lane": "rawstyle", "file": _track(tmp_path, "c", 150, seed=4)}]
    ordered = sorted(tracks, key=lambda t: t["bpm"])
    audio, chapters = mix.join(ordered, bars=2)
    assert [c["title"] for c in chapters] == ["Slow One", "Let\u2019s F*cking Go!", "Fast One"]
    assert chapters[0]["start_s"] == 0.0 and chapters[0]["start_s"] < chapters[1]["start_s"] < chapters[2]["start_s"]
    total = len(audio) / 48000
    assert 45 < total < 60, total          # three 20 s tracks minus two crossfades of two bars
    assert np.abs(audio).max() <= 1.5 and audio.dtype == np.float32
    assert mix.stamp(65) == "1:05" and mix.stamp(3725) == "1:02:05"


def test_period_window_volume_and_words():
    p = load_profile()
    assert mix.period_window("2026-09-27", "week") == ("2026-09-21", "2026-09-27")
    assert mix.period_window("2026-09-30", "month") == ("2026-09-01", "2026-09-30")
    cat = {"drops": [{"id": d, "date": d, "title": f"T{i}", "bpm": 150 + i, "lane": "industrial", "audio_url": "https://x/a.mp3", "status": "sent"}
                     for i, d in enumerate(("2026-09-21", "2026-09-23", "2026-09-27", "2026-09-10"))],
           "mixes": [{"id": "m1", "period": "week"}]}
    assert [d["id"] for d in mix.pick_tracks(cat, "2026-09-27", "week")] == ["2026-09-21", "2026-09-23", "2026-09-27"]
    assert mix.volume_number(cat, "week") == 2 and mix.volume_number(cat, "month") == 1
    chapters = [{"id": "x", "title": "T1", "bpm": 150, "lane": "industrial", "start_s": 0.0},
                {"id": "y", "title": "T2", "bpm": 154, "lane": "acid", "start_s": 148.5}]
    w = mix.words(p, chapters, "week", 2, 300.0, "2026-09-27")
    assert w["title"].startswith("Industrial Hard Techno Mix 2026 | ANCHOR Vol. 2 | 2 tracks, 5 min") and len(w["title"]) <= 100
    assert "0:00 T1 (150 BPM)" in w["description"] and "2:28 T2 (154 BPM)" in w["description"]
    assert w["description"].splitlines()[0].startswith("Industrial Hard Techno mix, 5 minutes, 2 original ANCHOR tracks")
    assert "hard techno mix 2026" in w["tags"] and "acid techno" in w["tags"] and len(w["tags"]) <= 40
    assert "—" not in w["description"] and "!" not in w["title"]


def test_build_makes_audio_cover_video_and_chapters_from_the_period(fast_profile, tmp_path, monkeypatch):
    p = fast_profile
    files = {d: _track(tmp_path, d, bpm, seconds=18, seed=i) for i, (d, bpm) in
             enumerate((("2026-09-21", 150), ("2026-09-23", 155), ("2026-09-25", 152)), 1)}
    cat = {"drops": [{"id": d, "date": d, "title": f"Track {d[-2:]}", "bpm": bpm, "lane": "industrial", "family": p.families[0].id,
                      "seed": 5, "audio_url": f"file://{files[d]}", "status": "sent"} for d, bpm in (("2026-09-21", 150), ("2026-09-23", 155), ("2026-09-25", 152))]}
    monkeypatch.setattr(mix.urllib.request, "urlretrieve", lambda url, dst: Path(dst).write_bytes(Path(url[7:]).read_bytes()))
    meta = mix.build(p, cat, "2026-09-27", "week", tmp_path / "out", art_mode="procedural")
    out = tmp_path / "out"
    assert (out / meta["files"]["mp3"]).exists() and (out / meta["files"]["full_169"]).exists() and (out / "frame-169.jpg").exists()
    assert [c["bpm"] for c in meta["chapters"]] == [150, 152, 155] and meta["vol"] == 1
    assert 30 < meta["duration_s"] < 54 and abs(meta["video"]["duration"] - meta["duration_s"]) < 1.5
    assert meta["title"].startswith("Industrial Hard Techno Mix 2026 | ANCHOR Vol. 1")
    # record: a row in the catalog and a ledger entry
    (out / "publish.json").write_text(json.dumps({"youtube": {"post_id": "v9", "status": "scheduled", "external_link": "https://youtu.be/v9"}}))
    site = tmp_path / "site"; (site / "data").mkdir(parents=True)
    catp = site / "data" / "catalog.json"; catp.write_text(json.dumps(cat))
    row = pipeline.record_mix(p, out, repo="o/r", catalog_path=catp, site_dir=site)
    assert row["id"] == "mix-week-2026-09-27" and row["youtube_url"] == "https://youtu.be/v9" and row["tracks"] == ["2026-09-21", "2026-09-25", "2026-09-23"]
    assert (site / "covers" / "mix-week-2026-09-27.jpg").exists()
    saved = json.loads(catp.read_text())
    assert saved["mixes"][0]["id"] == row["id"] and len(saved["drops"]) == 3
    book = json.loads((site / "data" / "ledger.json").read_text())
    assert book["entries"][0]["source"] == "mix" and book["entries"][0]["uploads"][0]["url"] == "https://youtu.be/v9"
    with pytest.raises(RuntimeError):
        mix.build(p, {"drops": cat["drops"][:2]}, "2026-09-27", "week", tmp_path / "out2")


# ---------------------------------------------------------------------- retitle
def test_retitle_rewrites_only_what_differs_and_is_idempotent(monkeypatch, tmp_path):
    from anchor import retitle
    p = load_profile()
    updates = []

    class FakeApi:
        def channel_videos(self, channel_id):
            return [
                {"id": "kbMQz4tWUtU", "title": "Rupture Pulse", "categoryId": "10", "tags": ["t"],
                 "description": "Warehouse pressure with no off switch.\n\nIndustrial Hard Techno · 154 BPM · ANCHOR\nAll tracks: https://p\nFree download: site\n\n#a #b #c"},
                {"id": "done1", "title": "Pull Under | Industrial Hard Techno | ANCHOR", "categoryId": "10", "tags": [],
                 "description": "Industrial Hard Techno. An ANCHOR original, free download below.\n\nThe current wins."},
                {"id": "robot1", "title": "Cold Iron Sky", "categoryId": "10", "tags": [],
                 "description": "Cold and clean.\n\nAcid Techno · 150 BPM · ANCHOR\nAll tracks: https://p"},
                {"id": "mystery", "title": "Something Else", "categoryId": "10", "tags": [], "description": "x"},
            ]

        def update_video(self, video, *, title, description, tags=None):
            updates.append((video["id"], title, description))

    channel = tmp_path / "channel.json"
    channel.write_text(json.dumps({"videos": {"kbMQz4tWUtU": {"title": "Rupture Pulse", "genre": "Industrial Hard Techno", "bpm": 154},
                                              "done1": {"title": "Pull Under", "genre": "Industrial Hard Techno", "bpm": None}}}))
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps({"drops": [{"id": "2026-09-24", "title": "Cold Iron Sky", "lane": "acid", "bpm": 150,
                                          "youtube_url": "https://www.youtube.com/watch?v=robot1"}]}))
    r = retitle.run(p, catalog_path=cat, channel_path=channel, api=FakeApi())
    assert [u[0] for u in updates] == ["kbMQz4tWUtU", "robot1"] and r["same"] == ["done1"] and r["unknown"] == ["mystery"]
    assert updates[0][1] == "Rupture Pulse | Industrial Hard Techno 154 BPM | ANCHOR"
    assert updates[0][2] == ("Industrial Hard Techno at 154 BPM. An ANCHOR original, free download below.\n\n"
                             "Warehouse pressure with no off switch.\n\nAll tracks: https://p\nFree download: site\n\n#a #b #c")
    assert updates[1][1] == "Cold Iron Sky | Acid Techno 150 BPM | ANCHOR" and updates[1][2].startswith("Acid Techno at 150 BPM. An ANCHOR original")
    # a second pass over the rewritten text changes nothing
    again = retitle.rewrite_description(updates[0][2], "Industrial Hard Techno", 154, "ANCHOR")
    assert again == updates[0][2]
    assert retitle.search_title("X" * 95, "Industrial Hard Techno", 154, "ANCHOR") == "X" * 95
