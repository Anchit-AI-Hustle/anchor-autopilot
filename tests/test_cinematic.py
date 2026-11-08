"""Cinematic videos (Anchit, 2026-11-08): LTX-Video shots made only while the Mac is idle, cut to the beat."""
import importlib.util
import itertools
from pathlib import Path

from anchor import cinematic

ROOT = Path(__file__).resolve().parents[1]
SECS = [{"start": 0.0, "end": 22.4, "kind": "intro"}, {"start": 22.4, "end": 67.0, "kind": "groove"},
        {"start": 67.0, "end": 89.3, "kind": "breakdown"}, {"start": 89.3, "end": 145.0, "kind": "drop"},
        {"start": 145.0, "end": 160.0, "kind": "outro"}]


def test_the_edit_covers_the_song_and_cuts_on_bar_lines():
    for bpm in (160, 172, 186, 200):
        off, dur = 0.31, 160.0
        edit = cinematic.plan(SECS, dur, bpm, off, 6, 4.04)
        assert edit[0]["n0"] == 0 and edit[-1]["n1"] == round(dur * cinematic.FPS)
        for a, b in itertools.pairwise(edit):
            assert a["n1"] == b["n0"]                                  # contiguous, no gap, no overlap
            assert a["shot"] != b["shot"]                              # never the same shot twice in a row
        bar = 240 / bpm
        starts = {round(s["start"] * cinematic.FPS) for s in SECS}
        for seg in edit:
            if seg["n0"] in starts:
                continue
            beats_from_grid = (seg["start"] - off) / bar
            assert abs(beats_from_grid - round(beats_from_grid)) * bar < 1.5 / cinematic.FPS, (bpm, seg)
        for seg in edit:
            n = seg["n1"] - seg["n0"]
            assert seg["src"] + n <= int(4.04 / seg["speed"] * cinematic.FPS)   # the shot is long enough
            assert n <= 4 * bar * cinematic.FPS + 1


def test_calm_sections_hold_longer_and_play_slower():
    edit = cinematic.plan(SECS, 160.0, 172, 0.0, 6, 4.04)
    calm = [s for s in edit if s["kind"] in cinematic.CALM]
    busy = [s for s in edit if s["kind"] not in cinematic.CALM]
    assert all(s["speed"] < 1 for s in calm) and all(s["speed"] == 1 for s in busy)
    avg = lambda xs: sum(s["n1"] - s["n0"] for s in xs) / len(xs)
    assert avg(calm) > avg(busy)


def test_every_shot_is_used_and_varied():
    edit = cinematic.plan(SECS, 160.0, 172, 0.0, 6, 4.04)
    assert {s["shot"] for s in edit} == set(range(6))
    assert any(s["flip"] for s in edit) and any(not s["flip"] for s in edit)
    assert len({s["src"] for s in edit}) > 1                           # head and tail of the shots both show


def test_a_song_needs_enough_shots(tmp_path):
    d = tmp_path / "some-song"
    d.mkdir()
    for n in range(1, cinematic.MIN_SHOTS):
        (d / f"shot-{n:02d}.mp4").write_bytes(b"x" * 20_000)
    (d / "shot-9.part.mp4").write_bytes(b"x" * 20_000)               # a shot still being written
    assert cinematic.shots_for("some-song", tmp_path) == []
    (d / f"shot-{cinematic.MIN_SHOTS:02d}.mp4").write_bytes(b"x" * 20_000)
    assert len(cinematic.shots_for("some-song", tmp_path)) == cinematic.MIN_SHOTS
    assert cinematic.shots_for(None, tmp_path) == [] and cinematic.shots_for("other", tmp_path) == []


def _worker():
    spec = importlib.util.spec_from_file_location("cin_worker", ROOT / "tools" / "cinematic" / "worker.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_worker_only_runs_on_an_idle_mac_on_mains(monkeypatch):
    w = _worker()
    state = {"batt": "Now drawing from 'AC Power'", "idle": 900, "free": 70, "level": 1, "ps": "/sbin/launchd"}

    def run(cmd):
        if cmd[0] == "pmset":
            return state["batt"]
        if cmd[0] == "ioreg":
            return f'    | | |   "HIDIdleTime" = {int(state["idle"] * 1e9)}'
        if cmd[0] == "memory_pressure":
            return f"System-wide memory free percentage: {state['free']}%"
        if cmd[0] == "sysctl":
            return f"{state['level']}\n"
        return state["ps"]

    monkeypatch.setattr(w, "_run", run)
    assert w.why_not() is None
    state["batt"] = "Now drawing from 'Battery Power'"
    assert w.why_not() == "on battery"
    state["batt"] = "Now drawing from 'AC Power'"
    state["idle"] = 30
    assert "in use" in w.why_not()
    assert "in use" not in (w.why_not(running=True) or "")              # running: any touch in the last 5 s stops it
    state["idle"] = 2
    assert "in use" in w.why_not(running=True)
    state["idle"] = 900
    state["ps"] = "/Users/x/actions-runner-anchor/bin/Runner.Worker spawnclient 1 2"
    assert w.why_not() == "a song is being made"
    state["ps"] = "/sbin/launchd"
    state["free"] = 30
    assert "memory" in w.why_not()
    assert w.why_not(running=True) is None                             # our own model is what fills memory then
    state["level"] = 2
    assert w.why_not(running=True) == "memory pressure rising"


def test_every_unreleased_song_has_a_twelve_shot_storyboard_from_its_lyrics():
    """Anchit, 2026-11-09: "need more related videos after understanding the music and its storyline"."""
    from anchor import songbook
    w = _worker()
    w.REPO = ROOT
    boards = w.storyboards()
    for song in songbook.load():
        board = boards.get(song.id)
        assert board and len(board) == 12, song.id
        assert sum(b["hook"] for b in board) == 3, song.id
        tags = {t.strip().strip("[]").lower() for t in song.lyrics.splitlines() if t.startswith("[")}
        for b in board:
            words = len(b["prompt"].split())
            assert 30 <= words <= 80, (song.id, words)
            assert "—" not in b["prompt"] and "–" not in b["prompt"]
            assert b["part"].lower() in tags, (song.id, b["part"], tags)
    first = songbook.load()[0].id
    shots = w.shots({"id": first, "about": "x"}, boards)
    assert len(shots) == 12 and shots[0]["prompt"] == boards[first][0]["prompt"]
    # a song without a storyboard falls back to the six template shots
    assert len(w.shots({"id": "nope", "about": "a test", "groups": ["psy"]}, boards)) == 6


def test_the_template_shots_fit_the_music():
    w = _worker()
    w.REPO = ROOT
    songs = w.songbook()
    hard = next(s for s in songs if s["groups"][0] == "hardtech")
    psy = next(s for s in songs if s["groups"][0] == "psy")
    assert "night" in w.template_shots(hard)[0] and "dawn" in w.template_shots(psy)[0]
    a = next(s for s in songs if s.get("model") == "A")
    b = next(s for s in songs if s.get("model") == "B")
    assert "handheld" in " ".join(w.template_shots(a)) and "handheld" not in " ".join(w.template_shots(b))


def test_story_shots_follow_the_song_and_the_hook_brings_its_own():
    story, hooks = [0, 1, 2, 3, 4, 5, 6, 7, 8], [9, 10, 11]
    windows = [(40.0, 52.0), (110.0, 122.0)]
    edit = cinematic.plan(SECS, 160.0, 172, 0.0, 12, 4.04, story=story, hooks=hooks, hook_times=windows)
    for seg in edit:
        mid = (seg["start"] + seg["end"]) / 2
        assert (seg["shot"] in hooks) == any(a <= mid < b for a, b in windows)
    order = [story.index(s["shot"]) for s in edit if s["shot"] in story]
    assert order[0] <= 1 and order[-1] >= len(story) - 2          # starts at the start, ends at the end
    for seg in edit:                                              # each shot plays in its own part of the song
        if seg["shot"] in story:
            slot = int((seg["start"] + seg["end"]) / 2 / 160.0 * len(story))
            assert story.index(seg["shot"]) in (slot - 1, slot, slot + 1)
    for a, b in itertools.pairwise(edit):
        assert a["shot"] != b["shot"]


def test_hook_windows_come_from_the_hook_section_of_the_sheet():
    lyrics = "[Verse 1]\nI walk the line\n[Hook]\nOutrun your shadow\nRun, run\n[Verse 2]\nI walk the line again\n"
    lines = [{"start": 1.0, "end": 3.0, "text": "I walk the line"},
             {"start": 4.0, "end": 6.0, "text": "Outrun your shadow!"},
             {"start": 6.5, "end": 7.0, "text": "run run"},
             {"start": 8.0, "end": 9.0, "text": "I walk the line again"}]
    assert cinematic.hook_windows(lines, lyrics) == [(4.0, 7.2), (6.5, 8.2)]
    assert cinematic.hook_windows(None, lyrics) == [] and cinematic.hook_windows(lines, "") == []


def test_shot_roles_and_ready_songs(tmp_path):
    import json as _json
    d = tmp_path / "song-a"
    d.mkdir()
    shots = []
    for n in range(1, 5):
        p = d / f"shot-{n:02d}.mp4"
        p.write_bytes(b"x" * 20_000)
        p.with_suffix(".json").write_text(_json.dumps({"hook": n == 3}))
        shots.append(p)
    assert cinematic.roles(shots) == ([0, 1, 3], [2])
    assert cinematic.ready_ids(tmp_path) == set()
    (d / "complete").write_text("x")
    assert cinematic.ready_ids(tmp_path) == {"song-a"}


def test_a_song_with_its_shots_ready_is_picked_first():
    import random as _random

    from anchor import songbook
    songs = songbook.load()
    want = [s for s in songs if "rap" in s.groups][-1]
    assert songbook.pick(songs, "rap", _random.Random(3), [], prefer={want.id}).id == want.id


def test_the_worker_shoots_songs_queued_for_the_cinematic_look_first(tmp_path):
    import json as _json
    w = _worker()
    (tmp_path / "queue").mkdir()
    (tmp_path / "queue" / "queue.json").write_text(_json.dumps({
        "10-x.m4a": {"title": "Night Shift", "tags": "psytrance, 145 bpm", "suno_id": "abc", "style": "cinematic",
                     "lyrics": "[Verse]\nwe ride at dawn\n"},
        "11-y.m4a": {"title": "Other", "tags": "techno", "suno_id": "def", "style": "motion"}}))
    w.REPO = tmp_path
    q = w.queued_cinematic()
    assert [s["id"] for s in q] == ["abc"] and q[0]["groups"] == ["psy"] and "we ride at dawn" in q[0]["about"]


def test_the_cinematic_render_fills_both_screens(tmp_path):
    """A real short render: the 16:9 and the 9:16 come out full size from square shots."""
    import subprocess as sp

    from anchor.video import media_summary
    shots = []
    for n in range(1, 5):
        p = tmp_path / f"shot-{n:02d}.mp4"
        sp.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=704x704:rate=24:duration=4.04",
                "-pix_fmt", "yuv420p", str(p)], check=True)
        shots.append(p)
    audio = tmp_path / "a.wav"
    sp.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=12", str(audio)], check=True)
    secs = [{"start": 0.0, "end": 6.0, "kind": "build"}, {"start": 6.0, "end": 12.0, "kind": "drop"}]
    for vert, size in ((False, (1920, 1080)), (True, (1080, 1920))):
        out = tmp_path / f"v{vert}.mp4"
        info = cinematic.render_cinematic_video(shots, audio, out, "#ff3bd4", secs, "TEST", "hard techno",
                                                tmp_path / f"w{vert}", bpm=172, beat_offset=0.0, lines=[],
                                                vertical=vert)
        assert (info["width"], info["height"]) == size and abs(info["duration"] - 12) < 0.3
        assert media_summary(out)["duration"] > 11.5
