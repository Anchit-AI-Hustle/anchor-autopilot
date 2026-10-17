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

    out = uploads.run(load_profile(), repo="o/r", work=tmp_path, api=Api(), path=path, catalog_path=tmp_path / "none.json",
                      read=lambda url: {"render": 3})
    assert len(out["uploaded"]) == 3 and out["private"] == ["OLD0", "OLD1", "OLD2"]
    assert calls[0] == ("up", "f0.mp4") and calls[1] == ("private", "OLD0")      # old goes private only after the new is up


def test_older_songs_get_motion_videos_and_keep_their_genre(tmp_path, monkeypatch):
    import json as _j
    from anchor import motion
    from anchor.config import load_profile
    monkeypatch.setattr(motion, "LEGACY_PATH", uploads.UPLOADS_PATH.parent / "legacy_motion.json")
    legacy = _j.loads((uploads.UPLOADS_PATH.parent / "legacy_motion.json").read_text())["songs"]
    ids = [d["id"] for d in motion.songs({"drops": []})]
    assert ids == [d["id"] for d in legacy] and len(ids) == 9
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


def test_held_and_taken_down_songs_are_never_posted_again(monkeypatch):
    import json as _j
    from anchor import motion
    from anchor.config import load_profile
    legacy = uploads.UPLOADS_PATH.parent / "legacy_motion.json"
    monkeypatch.setattr(motion, "LEGACY_PATH", legacy)
    hold = _j.loads(legacy.read_text())["hold"]
    assert {"2026-10-10", "2026-09-20", "2026-09-24", "2026-09-12"} <= set(hold)
    catalog = {"drops": [{"id": "2026-10-10", "title": "Liquid Cipher", "date": "2026-10-10", "bpm": 167, "family": "prism",
                          "lane": "rawstyle", "audio_url": "https://x/ANCHOR-2026-10-10-liquid-cipher.mp3"}]}
    data = {"uploads": []}
    added = uploads.queue_motion(load_profile(), data, catalog, "o/r", [], exists=lambda url: True)
    assert "motion-2026-10-10" not in added


def test_a_top_up_motion_run_lists_only_the_new_songs(tmp_path, monkeypatch):
    import json as _j
    from anchor import motion
    monkeypatch.setattr(motion, "LEGACY_PATH", uploads.UPLOADS_PATH.parent / "legacy_motion.json")
    only = tmp_path / "only.json"
    only.write_text(_j.dumps({"ids": ["legacy-cut-loose", "legacy-absolute-force"]}))
    assert motion.list_ids({"drops": []}, only) == ["legacy-cut-loose", "legacy-absolute-force"]
    only.write_text(_j.dumps({"ids": []}))
    assert len(motion.list_ids({"drops": []}, only)) == 9


def test_a_lyric_less_motion_upload_is_redone_and_its_old_one_goes_private(tmp_path):
    from anchor.config import load_profile
    catalog = {"drops": [{"id": "2026-10-16", "title": "Supersonic Current", "date": "2026-10-16", "bpm": 180, "family": "neon",
                          "lane": "hyper", "audio_url": "https://x/drop-2026-10-16/ANCHOR-2026-10-16-supersonic-current.mp3"}]}
    videos = [{"id": "NOLYRICS", "title": "Supersonic Current | Hyper Techno | ANCHOR", "duration": "PT2M45S", "privacy": "public",
               "description": "Hyper Techno.\n\n" + uploads.MARK}]
    data = {"uploads": [], "superseded": [{"id": "motion-2026-10-16", "youtube_url": "https://www.youtube.com/watch?v=NOLYRICS"}]}
    assert uploads.queue_motion(load_profile(), data, catalog, "o/r", videos, exists=lambda url: True) == ["motion-2026-10-16"]
    e = data["uploads"][0]
    assert not e.get("youtube_url") and not e.get("adopted") and e["replaces"] == ["NOLYRICS"]


def test_a_queued_song_uploaded_by_hand_later_is_adopted_not_uploaded_twice(tmp_path, monkeypatch):
    import json as _j
    from anchor.config import load_profile
    p = load_profile()
    data = {"uploads": [{"id": "motion-2026-10-09", "release": "drop-2026-10-09", "file": "f.mp4",
                         "title": "Transmit Spiral | Psychedelic Techno | ANCHOR", "description": "d", "replaces": ["OLD"]}]}
    videos = [{"id": "OLD", "title": "Transmit Spiral | Psychedelic Techno | ANCHOR", "duration": "PT2M40S", "privacy": "public", "description": "old"},
              {"id": "HAND", "title": "Transmit Spiral | Psychedelic Techno | ANCHOR", "duration": "PT2M40S", "privacy": "public",
               "description": "Psychedelic Techno.\n\n" + uploads.MARK}]
    path = tmp_path / "u.json"
    path.write_text(_j.dumps(data))
    calls = []

    class Api:
        def channel_videos(self, cid): return videos
        def upload(self, *a, **k): calls.append("UPLOAD")
        def set_privacy(self, vid, privacy): calls.append((privacy, vid))

    out = uploads.run(p, repo="o/r", work=tmp_path, api=Api(), path=path, catalog_path=tmp_path / "none.json", exists=lambda url: False)
    e = _j.loads(path.read_text())["uploads"][0]
    assert out["adopted"] == ["motion-2026-10-09"] and e["youtube_url"].endswith("HAND") and e["replaces"] == ["OLD"]
    assert calls == [("private", "OLD")]


def test_a_song_held_after_it_was_queued_never_goes_up():
    data = {"uploads": [{"id": "motion-2026-10-10", "youtube_url": None}, {"id": "motion-2026-10-09", "youtube_url": None},
                        {"id": "lyric-video", "youtube_url": None}]}
    assert [e["id"] for e in uploads.pending(data, {"2026-10-10": "held"})] == ["motion-2026-10-09", "lyric-video"]


def test_the_three_lyric_less_uploads_are_marked_for_redoing():
    import json as _j
    d = _j.loads(uploads.UPLOADS_PATH.read_text())
    assert {"44u-IjIQaW4", "QIPY1Y02Ylg", "eughYejQE3E", "LZCfgssUrRQ", "FCzjk1aLAtw", "cJ7giocxlvU"} <= uploads.superseded(d)
    assert not {"motion-2026-10-16", "motion-2026-10-13", "motion-2026-10-12", "motion-2026-10-09", "motion-2026-10-08",
                "motion-2026-10-05"} & {e["id"] for e in d["uploads"] if e.get("youtube_url")}


def test_an_old_render_waits_for_the_beat_locked_one(tmp_path, monkeypatch):
    import json as _j
    from anchor import motion
    from anchor.config import load_profile
    assert motion.RENDER >= 2
    path = tmp_path / "uploads.json"
    path.write_text(_j.dumps({"uploads": [{"id": f"motion-{i}", "release": f"drop-{i}", "file": f"ANCHOR-{i}-full-169.mp4",
                                            "title": "T", "description": "d", "replaces": []} for i in ("old", "new")]
                              + [{"id": "lyric", "release": "x", "file": "l.mp4", "title": "L", "description": "d"}]}))
    monkeypatch.setattr(uploads, "fetch", lambda url, dst, n: dst)
    seen = []

    class Api:
        def channel_videos(self, cid): return []
        def upload(self, video, **k): seen.append(video.name); return {"id": "N" + video.name}
        def add_to_playlist(self, vid, pl): pass

    marks = {"ANCHOR-old-motion.json": {"lyrics_lines": 4}, "ANCHOR-new-motion.json": {"render": 3}}
    out = uploads.run(load_profile(), repo="o/r", work=tmp_path, api=Api(), path=path, catalog_path=tmp_path / "none.json",
                      read=lambda url: marks.get(url.rsplit("/", 1)[-1], {}))
    assert seen == ["ANCHOR-new-full-169.mp4", "l.mp4"]
    assert not _j.loads(path.read_text())["uploads"][0].get("youtube_url")       # waits, goes up after the re-render


def test_movement_surges_on_the_kick_and_karaoke_lights_when_sung(tmp_path):
    from anchor import scenes
    from anchor.video import beat_step_expr
    e = beat_step_expr(120, 0.1, 0.0)
    ev = lambda t: eval(e.replace("floor", "__import__('math').floor").replace("pow", "__import__('math').pow"), {"t": t})
    assert abs(ev(0.1) - 0.0) < 1e-6 and abs(ev(0.6) - 1.0) < 1e-6         # one step per beat, landing on the kick
    assert ev(0.35) > 0.9                                                    # most of the move is done half a beat after the kick
    lines = [{"start": 10.0, "end": 11.0, "words": [("hey", 10.0, 10.4), ("you", 10.5, 11.0)]}]
    secs = [{"kind": "intro", "start": 0.0, "end": 8.0}, {"kind": "drop", "start": 8.0, "end": 20.0}]
    ass = scenes.write_ass(tmp_path / "a.ass", "#ff8800", 1920, 1080, secs, lines, "T", "S").read_text()
    cap = [l for l in ass.splitlines() if ",Cap," in l][0]
    assert cap.split(",")[1] == "0:00:09.80" and "{\\k20}{\\kf40}HEY" in cap   # 0.2 s lead before the first word lights
    for look in ("mirror", "corridor", "spectrum"):
        g = ";".join(scenes._scene(look, 1, 1920, 1080, {"kind": "drop"}, 300, 600, 150, 0.05, False))
        assert "floor(" in g and "(t+10.0000)*0.25" not in g


def test_every_old_full_video_of_the_song_goes_private_even_if_missed_when_queued(tmp_path, monkeypatch):
    import json as _j
    from anchor.config import load_profile
    path = tmp_path / "uploads.json"
    path.write_text(_j.dumps({"uploads": [{"id": "motion-2026-09-09", "release": "drop-2026-09-09", "file": "ANCHOR-x-full-169.mp4",
                                            "title": "Let’s F*cking Go! | Rawstyle Hybrid | ANCHOR", "description": "d", "replaces": []}]}))
    monkeypatch.setattr(uploads, "fetch", lambda url, dst, n: dst)
    videos = [{"id": "OLD", "title": "Let's F*cking Go | Rawstyle Hybrid | ANCHOR", "duration": "PT2M47S", "privacy": "public", "description": ""},
              {"id": "SHORT", "title": "Let's F*cking Go | Rawstyle Hybrid | ANCHOR", "duration": "PT45S", "privacy": "public", "description": ""}]
    calls = []

    class Api:
        def channel_videos(self, cid): return videos
        def upload(self, video, **k): calls.append("up"); return {"id": "NEW"}
        def add_to_playlist(self, vid, pl): pass
        def set_privacy(self, vid, privacy): calls.append((privacy, vid))

    out = uploads.run(load_profile(), repo="o/r", work=tmp_path, api=Api(), path=path, catalog_path=tmp_path / "none.json",
                      exists=lambda url: False, read=lambda url: {"render": 3})
    assert calls == ["up", ("private", "OLD")] and out["private"] == ["OLD"]


def test_old_thumbnails_are_redrawn_without_the_tempo(tmp_path, monkeypatch):
    from PIL import Image
    from anchor import thumbs
    assert thumbs.genre_of("Cold Bunker | Rawstyle Hybrid | ANCHOR") == "Rawstyle Hybrid"
    assert thumbs.genre_of("Cold Bunker | Rawstyle Hybrid 155 BPM | ANCHOR") == "Rawstyle Hybrid"
    cat = uploads.UPLOADS_PATH.parent / "catalog.json"                                 # the real one (conftest hides it)
    src = thumbs.sources("o/r", cat)
    assert {"coldbunker", "nocontrol", "fallinside"} <= set(src)                    # catalogue, older songs, one-off uploads
    videos = [{"id": "FULL", "title": "Cold Bunker | Rawstyle Hybrid | ANCHOR", "privacy": "public", "description": "old"},
              {"id": "SHORT", "title": "Cold Bunker | Rawstyle Hybrid | ANCHOR", "privacy": "public", "description": "old"},
              {"id": "MOTION", "title": "Cold Bunker | Rawstyle Hybrid | ANCHOR", "privacy": "public", "description": uploads.MARK},
              {"id": "GONE", "title": "Cold Bunker | Rawstyle Hybrid | ANCHOR", "privacy": "private", "description": ""},
              {"id": "MIX", "title": "Some Mix | ANCHOR", "privacy": "public", "description": ""}]
    sizes = {}

    class Api:
        def set_thumbnail(self, vid, image):
            sizes[vid] = Image.open(image).size
            assert Path(image).stat().st_size < 2_000_000                            # YouTube's limit

    data = {"uploads": []}
    out = thumbs.run(Api(), videos, data, "o/r", tmp_path, "ANCHOR", uploads.MARK, short_test=lambda v: v == "SHORT",
                     catalog_path=cat)
    assert out == ["FULL", "SHORT"] and sizes == {"FULL": (1920, 1080), "SHORT": (1080, 1920)}
    assert thumbs.run(Api(), videos, data, "o/r", tmp_path, "ANCHOR", uploads.MARK, short_test=lambda v: False,
                      catalog_path=cat) == []                                         # once


def test_no_cover_carries_a_tempo():
    import subprocess
    import shutil
    import pytest
    from pathlib import Path
    if not shutil.which("tesseract"):
        pytest.skip("tesseract not installed")
    site = uploads.UPLOADS_PATH.parent.parent
    for f in sorted([*site.glob("covers/*.jpg"), *site.glob("legacy/*-cover.jpg")]):
        text = subprocess.run(["tesseract", str(f), "-", "--psm", "11"], capture_output=True, text=True).stdout
        assert "BPM" not in text.upper(), f.name


def test_a_sung_line_leaves_the_screen_after_its_last_word(tmp_path):
    from anchor import motion, scenes
    assert motion.RENDER >= 3
    lines = [{"start": 11.9, "end": 14.8, "words": [("And", 11.9, 12.3), ("we", 12.4, 12.8), ("are", 12.9, 13.4), ("taking", 13.5, 14.8)]},
             {"start": 73.6, "end": 74.9, "words": [("Welcome", 73.6, 74.1), ("to", 74.2, 74.4), ("Project", 74.5, 74.9)]}]
    secs = [{"kind": "intro", "start": 0.0, "end": 8.0}, {"kind": "drop", "start": 8.0, "end": 90.0}]
    ass = scenes.write_ass(tmp_path / "a.ass", "#ff8800", 1920, 1080, secs, lines, "T", "S").read_text()
    caps = [l.split(",") for l in ass.splitlines() if ",Cap," in l]
    assert caps[0][2] == "0:00:16.00"                      # gone 1.2 s after "taking", not at 73.4 s
