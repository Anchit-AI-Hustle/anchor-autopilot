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
    assert out == {"uploaded": ["e1 -> NEW1"], "errors": []}
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
    assert uploads.run(PROFILE, repo="o/r", work=tmp_path, api=None, path=path) == {"uploaded": [], "errors": []}


def test_the_lyric_video_entry_is_ready_to_go():
    data = json.loads(uploads.UPLOADS_PATH.read_text())
    e = next(x for x in data["uploads"] if x["id"] == "kindness-needs-truth-lyric-video")
    assert e["title"] == "Kindness Needs Truth (Lyric Video) | ANCHOR"
    assert len(e["description"]) <= 5000 and "[Chorus]" in e["description"]
    assert not any(c in e["description"] for c in "–—<>")
    assert e["file"].endswith(".mp4") and e["release"] == "extras-2026-09-28"
