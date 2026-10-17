"""One-off uploads: each pending entry goes up once, with its words, thumbnail and playlist,
and the link is written back. Nothing here touches the network."""
import json
import shutil
from pathlib import Path

from anchor import uploads
from anchor.config import load_profile

PROFILE = load_profile()


class FakeYouTube:
    def __init__(self, fail=()):
        self.uploads, self.thumbs, self.playlist, self.fail = [], [], [], set(fail)

    def upload(self, video, **kw):
        if kw["title"] in self.fail:
            raise RuntimeError("quotaExceeded")
        assert Path(video).exists()
        self.uploads.append(kw)
        return {"id": f"NEW{len(self.uploads)}", "url": f"https://youtu.be/NEW{len(self.uploads)}", "status": "public"}

    def set_thumbnail(self, vid, image):
        assert Path(image).exists()
        self.thumbs.append(vid)

    def add_to_playlist(self, vid, pl):
        self.playlist.append(vid)


def setup(tmp_path, monkeypatch, entries):
    src = tmp_path / "release"
    src.mkdir()
    for e in entries:
        (src / e["file"]).write_bytes(b"v" * 2_000_000)
        if e.get("thumbnail"):
            (src / e["thumbnail"]).write_bytes(b"j" * 20_000)

    def fake_fetch(url, dst, min_bytes=50_000):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src / url.rsplit("/", 1)[-1], dst)
        return dst

    monkeypatch.setattr(uploads, "fetch", fake_fetch)
    path = tmp_path / "uploads.json"
    path.write_text(json.dumps({"uploads": entries}))
    return path


def entry(i, **kw):
    return {"id": f"e{i}", "release": "extras", "file": f"v{i}.mp4", "thumbnail": f"t{i}.jpg",
            "title": f"Video {i} | ANCHOR", "description": f"words {i}", "tags": ["lyric video"], "youtube_url": None, **kw}


def test_each_pending_entry_goes_up_once_with_its_words(tmp_path, monkeypatch):
    path = setup(tmp_path, monkeypatch, [entry(1), entry(2, youtube_url="https://www.youtube.com/watch?v=OLD")])
    api = FakeYouTube()
    out = uploads.run(PROFILE, repo="o/r", work=tmp_path / "w", api=api, path=path)
    assert out["uploaded"] == ["e1 -> NEW1"] and out["errors"] == []
    up = api.uploads[0]
    assert up["title"] == "Video 1 | ANCHOR" and up["description"] == "words 1" and up["tags"] == ["lyric video"]
    assert up["privacy"] == "public" and up["ai_generated"] is True
    assert api.thumbs == ["NEW1"] and api.playlist == ["NEW1"]
    saved = json.loads(path.read_text())["uploads"]
    assert saved[0]["youtube_url"] == "https://www.youtube.com/watch?v=NEW1" and saved[0]["uploaded_at"]
    assert saved[1]["youtube_url"] == "https://www.youtube.com/watch?v=OLD"
    again = uploads.run(PROFILE, repo="o/r", work=tmp_path / "w", api=api, path=path)
    assert again["uploaded"] == [] and len(api.uploads) == 1        # never twice


def test_a_failed_upload_stays_pending_and_the_rest_go_up(tmp_path, monkeypatch):
    path = setup(tmp_path, monkeypatch, [entry(1), entry(2)])
    out = uploads.run(PROFILE, repo="o/r", work=tmp_path / "w", api=FakeYouTube(fail={"Video 1 | ANCHOR"}), path=path)
    assert out["uploaded"] == ["e2 -> NEW1"] and out["errors"] == ["e1: quotaExceeded"]
    assert [e["id"] for e in uploads.pending(json.loads(path.read_text()))] == ["e1"]


def test_nothing_pending_needs_no_credentials(tmp_path):
    path = tmp_path / "uploads.json"
    path.write_text(json.dumps({"uploads": [entry(1, youtube_url="https://www.youtube.com/watch?v=X")]}))
    out = uploads.run(PROFILE, repo="o/r", work=tmp_path, api=None, path=path)
    assert out["uploaded"] == [] and out["errors"] == []


def test_the_lyric_video_entry_is_ready_to_go():
    data = json.loads(uploads.UPLOADS_PATH.read_text())
    e = next(x for x in data["uploads"] if x["id"] == "kindness-needs-truth-lyric-video")
    assert e["title"] == "Kindness Needs Truth (Lyric Video) | ANCHOR"
    assert len(e["description"]) <= 5000 and "[Chorus]" in e["description"]
    assert not any(c in e["description"] for c in "–—<>")
    assert e["file"].endswith(".mp4") and e["release"] == "extras-2026-09-28"


def test_an_entry_can_go_up_without_telling_subscribers(tmp_path, monkeypatch):
    """A Short goes up quietly; subscribers are told once, by the full track."""
    path = setup(tmp_path, monkeypatch, [entry(1), entry(2, notify=False, playlist=False)])
    api = FakeYouTube()
    uploads.run(PROFILE, repo="o/r", work=tmp_path / "w", api=api, path=path)
    assert api.uploads[0]["notify"] is bool(PROFILE.youtube["notify_subscribers"])
    assert api.uploads[1]["notify"] is False
    assert api.playlist == ["NEW1"]


def test_fall_inside_full_track_and_short_are_ready_to_go():
    """Anchit, 2026-10-04: put Fall Inside (the free ACE-Step test song) on YouTube."""
    data = json.loads(uploads.UPLOADS_PATH.read_text())
    full = next(x for x in data["uploads"] if x["id"] == "fall-inside-full-track")
    short = next(x for x in data["uploads"] if x["id"] == "fall-inside-short")
    for e in (full, short):
        assert e["release"] == "drop-2026-10-04" and e["file"].startswith("ANCHOR-2026-10-04-fall-inside-")
        assert e["title"] == "Fall Inside | Acid Techno | ANCHOR"   # no tempo in a title
        assert len(e["description"]) <= 5000 and not any(c in e["description"] for c in "\u2013\u2014<>")
        assert "AI use disclosed" in e["description"]
    assert full["file"].endswith("-full-169.mp4") and full["thumbnail"].endswith("-frame-169.jpg")
    assert "frame-169.jpg" != full["thumbnail"], "a name of its own: the daily run reuses frame-169.jpg"
    assert short["file"].endswith("-short.mp4") and short["notify"] is False and short["playlist"] is False
    assert "shorts" in short["tags"]


def test_motion_videos_replace_the_old_full_video_and_never_show_a_tempo(tmp_path):
    from anchor import motion
    from anchor.config import load_profile
    assert "BPM" not in [l for l in (uploads.Path(motion.__file__).read_text().splitlines()) if "sub = " in l][0]
    p = load_profile()
    catalog = {"drops": [{"id": "2026-10-16", "title": "Supersonic Current", "date": "2026-10-16", "bpm": 180, "family": "neon",
                          "lane": "hyper", "audio_url": "https://github.com/o/r/releases/download/drop-2026-10-16/ANCHOR-2026-10-16-supersonic-current.mp3"},
                         {"id": "2026-10-13", "title": "Heavy Carbon", "date": "2026-10-13", "bpm": 170, "family": "neon",
                          "lane": "hard", "audio_url": "https://github.com/o/r/releases/download/drop-2026-10-13/ANCHOR-2026-10-13-heavy-carbon.mp3"}]}
    videos = [{"id": "OLDFULL", "title": "Supersonic Current | Hyper Techno | ANCHOR", "duration": "PT2M16S", "privacy": "public"},
              {"id": "SHORT", "title": "Supersonic Current | Hyper Techno | ANCHOR", "duration": "PT46S", "privacy": "public"},
              {"id": "OTHER", "title": "Heavy Carbon | Hard Techno | ANCHOR", "duration": "PT2M10S", "privacy": "public"}]
    data = {"uploads": []}
    added = uploads.queue_motion(p, data, catalog, "o/r", videos, exists=lambda url: "supersonic" in url)
    assert added == ["motion-2026-10-16"]                       # Heavy Carbon's motion video is not on its release yet
    e = data["uploads"][0]
    assert e["replaces"] == ["OLDFULL"] and e["file"] == "ANCHOR-2026-10-16-supersonic-current-full-169.mp4"
    assert "BPM" not in e["title"] and e["notify"] is False and e["playlist"] is True
    assert uploads.queue_motion(p, data, catalog, "o/r", videos, exists=lambda url: True) == ["motion-2026-10-13"]   # never twice
    assert uploads.seconds("PT2M16S") == 136 and uploads.seconds("PT46S") == 46 and uploads.seconds(None) == 0


def test_a_run_uploads_at_most_three_and_sets_the_replaced_video_private(tmp_path, monkeypatch):
    import json as _j
    from anchor.config import load_profile
    path = tmp_path / "uploads.json"
    path.write_text(_j.dumps({"uploads": [{"id": f"motion-{i}", "release": "r", "file": f"f{i}.mp4", "title": "T", "description": "d",
                                            "replaces": [f"OLD{i}"]} for i in range(5)]}))
    monkeypatch.setattr(uploads, "fetch", lambda url, dst, n: dst)
    calls = []

    class Api:
        def channel_videos(self, cid): return []
        def upload(self, video, **k): calls.append(("up", video.name)); return {"id": "NEW" + video.name}
        def add_to_playlist(self, vid, pl): pass
        def set_privacy(self, vid, privacy): calls.append((privacy, vid))

    out = uploads.run(load_profile(), repo="o/r", work=tmp_path, api=Api(), path=path, catalog_path=tmp_path / "none.json")
    assert len(out["uploaded"]) == 3 and out["private"] == ["OLD0", "OLD1", "OLD2"]
    assert calls[0] == ("up", "f0.mp4") and calls[1] == ("private", "OLD0")      # old goes private only after the new is up


def test_older_songs_get_motion_videos_and_keep_their_genre(tmp_path, monkeypatch):
    import json as _j
    from anchor import motion
    from anchor.config import load_profile
    monkeypatch.setattr(motion, "LEGACY_PATH", uploads.UPLOADS_PATH.parent / "legacy_motion.json")
    legacy = _j.loads((uploads.UPLOADS_PATH.parent / "legacy_motion.json").read_text())["songs"]
    ids = [d["id"] for d in motion.songs({"drops": []})]
    assert ids == [d["id"] for d in legacy] and len(ids) == 4
    for d in legacy:                                   # the files the render and the upload read are in the repo
        base = d["audio_url"].rsplit("/", 1)[-1]
        assert (uploads.UPLOADS_PATH.parent.parent / "legacy" / base).stat().st_size > 1_000_000
        assert (uploads.UPLOADS_PATH.parent.parent / d["cover"]).exists()
    p = load_profile()
    videos = [{"id": "OLDK", "title": "Kindness Needs Truth | Industrial Techno | ANCHOR", "duration": "PT4M14S", "privacy": "public"},
              {"id": "LYRIC", "title": "Kindness Needs Truth (Lyric Video) | ANCHOR", "duration": "PT4M14S", "privacy": "public"}]
    data = {"uploads": []}
    uploads.queue_motion(p, data, {"drops": []}, "o/r", videos, exists=lambda url: "kindness" in url)
    e = data["uploads"][0]
    assert e["title"] == "Kindness Needs Truth | Industrial Techno | ANCHOR" and e["replaces"] == ["OLDK"]   # the lyric video stays
    assert e["description"].startswith("Industrial Techno. An ANCHOR original") and "BPM" not in e["description"]
    assert e["release"] == "drop-legacy-kindness-needs-truth" and e["file"] == "ANCHOR-legacy-kindness-needs-truth-full-169.mp4"


def test_a_studio_upload_is_adopted_not_uploaded_again(tmp_path, monkeypatch):
    import json as _j
    from anchor.config import load_profile
    p = load_profile()
    catalog = {"drops": [{"id": "2026-09-28", "title": "Cold Bunker", "date": "2026-09-28", "bpm": 155, "family": "prism",
                          "lane": "rawstyle", "audio_url": "https://x/drop-2026-09-28/ANCHOR-2026-09-28-cold-bunker.mp3"}]}
    videos = [{"id": "OLD", "title": "Cold Bunker | Rawstyle Hybrid | ANCHOR", "duration": "PT2M30S", "privacy": "public", "description": "old"},
              {"id": "NEW", "title": "Cold Bunker | Rawstyle Hybrid | ANCHOR", "duration": "PT2M30S", "privacy": "public",
               "description": "Rawstyle Hybrid. An ANCHOR original\n\n" + uploads.MARK}]
    data = {"uploads": []}
    uploads.queue_motion(p, data, catalog, "o/r", videos, exists=lambda url: True)
    e = data["uploads"][0]
    assert e["adopted"] and e["youtube_url"].endswith("NEW") and e["replaces"] == ["OLD"] and uploads.MARK in e["description"]
    path = tmp_path / "u.json"
    path.write_text(_j.dumps(data))
    calls = []

    class Api:
        def channel_videos(self, cid): return videos
        def upload(self, *a, **k): calls.append("UPLOAD")
        def set_privacy(self, vid, privacy): calls.append((privacy, vid))

    out = uploads.run(p, repo="o/r", work=tmp_path, api=Api(), path=path, catalog_path=tmp_path / "none.json", exists=lambda url: True)
    assert calls == [("private", "OLD")] and out["private"] == ["OLD"] and not out["uploaded"]
    calls.clear()
    uploads.run(p, repo="o/r", work=tmp_path, api=Api(), path=path, catalog_path=tmp_path / "none.json", exists=lambda url: True)
    assert calls == []                                   # done once, never again
