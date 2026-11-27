"""Story videos from stills (anchor/storystills.py) and the Mac's filmed shots reaching every runner
(cinematic.fetch_released, tools/cinematic/worker.publish_complete). 2026-11-28 audit: every video
was the motion-graphics fallback because filmed shots existed for one song, on the Mac only."""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from anchor import cinematic, storystills
from anchor.video import media_summary

ROOT = Path(__file__).resolve().parent.parent


def fake_provider(calls):
    def make(prompt, seed):
        calls.append((prompt, seed))
        img = Image.new("RGB", (1024, 1024), ((seed * 37) % 255, 90, 140))
        for x in range(0, 1024, 64):                    # some detail so the moves are visible
            img.paste((255, 255, 255), (x, 500, x + 8, 524))
        return img
    return [("fake", make)]


def test_every_songbook_song_has_a_storyboard_of_twelve_shots_with_hooks():
    b = storystills.board("burn-the-blueprint")
    assert len(b) == 12 and sum(s["hook"] for s in b) == 3
    assert b[0]["part"] == "Intro" and "warehouse" in b[0]["prompt"]
    assert storystills.board("no-such-song") == [] and storystills.board(None) == []


@pytest.mark.parametrize("prompt,move", [
    ("fast handheld push in, subject centred", "push"),
    ("sweeping handheld crane over their heads", "pull"),
    ("low handheld tracking from behind", "track"),
    ("quick handheld whip up to the raised arm", "shake"),
    ("Slow drone push in", "pull"),
])
def test_the_camera_moves_the_way_the_storyboard_says(prompt, move):
    assert storystills.move_for(prompt) == move


def test_no_provider_means_no_stills_and_the_scene_video(monkeypatch, tmp_path):
    for k in ("CF_ACCOUNT_ID", "CF_API_TOKEN", "POLLINATIONS_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    assert storystills.providers() == []
    assert storystills.ensure("burn-the-blueprint", tmp_path) == []
    monkeypatch.setenv("CF_ACCOUNT_ID", "a")
    monkeypatch.setenv("CF_API_TOKEN", "t")
    assert [n for n, _ in storystills.providers()] == ["cloudflare-flux-schnell"]
    monkeypatch.setenv("POLLINATIONS_TOKEN", "p")
    assert [n for n, _ in storystills.providers()] == ["cloudflare-flux-schnell", "pollinations-flux"]


@pytest.mark.slow
def test_a_storyboard_becomes_twelve_moving_square_shots(tmp_path):
    calls = []
    shots = storystills.ensure("burn-the-blueprint", tmp_path, chain=fake_provider(calls))
    assert len(shots) == 12 and len(calls) == 12
    d = tmp_path / "burn-the-blueprint"
    assert (d / "complete").exists()
    m = media_summary(shots[0])
    assert abs(m["duration"] - storystills.SECONDS) < 0.1
    assert (m["width"], m["height"]) == (storystills.SIZE, storystills.SIZE)
    meta = json.loads((d / "shot-05.json").read_text())
    assert meta["hook"] is True and meta["source"] == "stills" and meta["provider"] == "fake"
    # the shot moves: first and last frame differ
    a, b = (subprocess.run(["ffmpeg", "-v", "error", "-ss", t, "-i", str(shots[0]), "-frames:v", "1",
                            "-f", "rawvideo", "-pix_fmt", "gray", "-s", "64x64", "-"], capture_output=True).stdout
            for t in ("0", "3.9"))
    assert a != b
    # a second run reuses everything
    assert storystills.ensure("burn-the-blueprint", tmp_path, chain=fake_provider(calls)) == shots
    assert len(calls) == 12
    # the cinematic cut reads the hooks
    story, hooks = cinematic.roles(shots)
    assert len(hooks) == 3 and len(story) == 9


def test_filmed_shots_come_before_still_made_ones(monkeypatch, tmp_path):
    def put(root, n):
        d = root / "song"
        d.mkdir(parents=True)
        for i in range(n):
            (d / f"shot-{i:02d}.mp4").write_bytes(b"x" * 20_000)
    monkeypatch.setenv("ANCHOR_CINEMATIC_DIR", str(tmp_path / "clips"))
    monkeypatch.setenv("ANCHOR_CINEMATIC_SYNC_DIR", str(tmp_path / "sync"))
    monkeypatch.setenv("ANCHOR_STILLS_DIR", str(tmp_path / "stills"))
    put(tmp_path / "stills", 12)
    assert all("stills" in str(p) for p in cinematic.shots_for("song"))
    put(tmp_path / "sync", 6)
    assert all("sync" in str(p) for p in cinematic.shots_for("song"))
    put(tmp_path / "clips", cinematic.MIN_SHOTS - 1)            # too few filmed: the synced set
    assert all("sync" in str(p) for p in cinematic.shots_for("song"))


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_macs_filmed_shots_are_fetched_from_their_release(monkeypatch, tmp_path):
    release = {"assets": [{"name": f"shot-{i:02d}.mp4", "browser_download_url": f"u/{i}.mp4"} for i in (1, 2)]
               + [{"name": "shot-01.json", "browser_download_url": "u/1.json"}, {"name": "notes.txt", "browser_download_url": "x"}]}
    seen = []

    def urlopen(req, timeout=0):
        url = getattr(req, "full_url", req)
        seen.append(url)
        if "releases/tags/cinematic-song" in url:
            return FakeResp(json.dumps(release).encode())
        if "releases/tags/" in url:
            raise OSError("404")
        return FakeResp(b"data-" + url.encode())
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    d = cinematic.fetch_released("song", tmp_path)
    assert sorted(p.name for p in d.iterdir()) == ["complete", "shot-01.json", "shot-01.mp4", "shot-02.mp4"]
    n = len(seen)
    assert cinematic.fetch_released("song", tmp_path) == d and len(seen) == n     # cached
    assert cinematic.fetch_released("other", tmp_path) is None


def test_the_worker_publishes_each_finished_set_once(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools" / "cinematic"))
    try:
        import worker
    finally:
        sys.path.pop(0)
    clips = tmp_path / "clips"
    for song, done in (("a", True), ("b", False)):
        d = clips / song
        d.mkdir(parents=True)
        (d / "shot-01.mp4").write_bytes(b"x")
        (d / "shot-01.json").write_text("{}")
        if done:
            (d / "complete").write_text("x")
    log = tmp_path / "calls"
    gh = tmp_path / "gh"
    gh.write_text(f"#!/bin/bash\necho \"$@\" >> {log}\n")
    gh.chmod(0o755)
    monkeypatch.setattr(worker, "LOG", tmp_path / "worker.log")
    assert worker.publish_complete(clips, gh=str(gh)) == ["a"]
    call = log.read_text()
    assert "release create cinematic-a" in call and "shot-01.mp4" in call and "cinematic-b" not in call
    assert (clips / "a" / "published").exists()
    assert worker.publish_complete(clips, gh=str(gh)) == []                     # once


def test_stills_get_the_scene_without_the_camera_directions():
    # 2026-11-28: "steady slow crane up" came back as a construction crane on the rooftop
    p = storystills.board("guarding-your-flame")[7]["prompt"]
    assert "crane" in p and "crane" not in storystills.scene_only(p)
    assert storystills.scene_only(p).startswith("A small bonfire on a rooftop")
    # a clause that also names the scene is kept whole
    q = "Handheld tracking shot behind a figure striding down a long corridor, harsh lights, whip pan, steady locked off frame"
    assert storystills.scene_only(q) == "Handheld tracking shot behind a figure striding down a long corridor, harsh lights"
    for b in storystills.board("burn-the-blueprint"):
        assert storystills.scene_only(b["prompt"]).split(",")[0] == b["prompt"].split(",")[0]


def test_a_provider_that_is_down_stops_after_three_misses(tmp_path):
    calls = []

    def down(prompt, seed):
        calls.append(seed)
        raise OSError("503")
    assert storystills.ensure("burn-the-blueprint", tmp_path, chain=[("down", down)]) == []
    assert len(calls) == 3 * 2            # three shots, two tries each, then it stops


def test_local_clips_are_used_without_touching_the_network(monkeypatch, tmp_path):
    d = tmp_path / "clips" / "song"
    d.mkdir(parents=True)
    for i in range(cinematic.MIN_SHOTS):
        (d / f"shot-{i:02d}.mp4").write_bytes(b"x" * 20_000)
    monkeypatch.setenv("ANCHOR_CINEMATIC_DIR", str(tmp_path / "clips"))
    monkeypatch.setattr(cinematic, "fetch_released", lambda *a, **k: pytest.fail("network"))
    assert len(cinematic.shots_for("song", sync=True)) == cinematic.MIN_SHOTS


def test_a_failed_download_of_synced_shots_never_breaks_the_drop(monkeypatch, tmp_path):
    release = {"assets": [{"name": "shot-01.mp4", "browser_download_url": "u/1.mp4"}]}

    def urlopen(req, timeout=0):
        url = getattr(req, "full_url", req)
        if "releases/tags/" in url:
            return FakeResp(json.dumps(release).encode())
        raise TimeoutError("slow")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert cinematic.fetch_released("song", tmp_path) is None
    assert not (tmp_path / "song" / "complete").exists()
