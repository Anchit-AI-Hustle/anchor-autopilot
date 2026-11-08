"""Cinematic videos (Anchit, 2026-11-08): LTX-Video shots made only while the Mac is idle, cut to the beat."""
import importlib.util
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
        for a, b in zip(edit, edit[1:]):
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
        (d / f"shot-{n}.mp4").write_bytes(b"x" * 20_000)
    (d / "shot-9.part.mp4").write_bytes(b"x" * 20_000)               # a shot still being written
    assert cinematic.shots_for("some-song", tmp_path) == []
    (d / f"shot-{cinematic.MIN_SHOTS}.mp4").write_bytes(b"x" * 20_000)
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


def test_the_worker_writes_six_story_shots_per_unreleased_song():
    w = _worker()
    w.REPO = ROOT
    songs = w.songbook()
    assert songs
    for s in songs[:5]:
        prompts = w.shots(s)
        assert len(prompts) == w.SHOTS == 6 and len(set(prompts)) == 6
        assert all(s["about"].rstrip(".") in p for p in prompts)
        assert not any("face" in p.lower() and "close" in p.lower() for p in prompts)
