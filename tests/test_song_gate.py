"""The hard song gate and the best of several takes (Anchit, 2026-10-24 and 2026-10-29: songs
were low quality; only songs that measure like real songs go out, and the Mac GPU renders
several takes so the best one ships)."""
import json
import time
from pathlib import Path

import numpy as np
import pytest

from anchor import pipeline, songgate
from anchor.audio import SR, decode, trim_tail
from anchor.music import FixtureEngine, renderer_settings, synth_techno, write_wav

# Anchit's own Suno songs measure between these (the gate's REFERENCE), so a take that sits
# inside them passes every check
SUNO_LIKE = {"duration_s": 210.0, "noise_score": 0.03, "melody_share": 0.85, "sound_movement": 0.2,
             "loud_quiet_range_db": 9.0, "most_different_parts": -0.4, "section_changes": 10, "silent_tail_s": 0.5}


def test_the_limits_are_the_publish_checks_own():
    """Same numbers as the publish check's script (Project doc claude/anchor-song-gate.py), so the
    robot and the check that watches it can never disagree about a file."""
    assert {k: v[:2] for k, v in songgate.CHECKS.items()} == {
        "noise_score": ("max", 0.0462), "melody_share": ("min", 0.7937), "sound_movement": ("min", 0.1296),
        "loud_quiet_range_db": ("min", 6.76), "most_different_parts": ("max", -0.2545),
        "section_changes": ("min", 7.1), "silent_tail_s": ("max", 3.0)}


def test_a_song_like_take_passes_and_each_miss_is_named():
    assert songgate.judge(SUNO_LIKE) == []
    # what the five songs of 2026-10-27 missed on (the publish check, 2026-10-28)
    misses = {**SUNO_LIKE, "melody_share": 0.643, "noise_score": 0.053, "silent_tail_s": 5.7}
    fails = songgate.judge(misses)
    assert [f["check"] for f in fails] == ["noise_score", "melody_share", "silent_tail_s"]
    lines = songgate.reasons({"fails": fails})
    assert lines[1] == "too little melody and harmony under the drums (melody_share 0.643, limit 0.7937)"
    assert lines[2] == "ends in dead air (silent_tail_s 5.7 s, limit 3.0)"


def test_the_score_ranks_takes_by_how_far_inside_the_limits_they_sit():
    better = {**SUNO_LIKE, "melody_share": 0.9, "section_changes": 14}
    assert songgate.score(better) > songgate.score(SUNO_LIKE) > 0
    assert songgate.score({**SUNO_LIKE, "melody_share": 0.643}) < songgate.score(SUNO_LIKE)
    assert songgate.score({}) == 0.0


def test_the_gate_is_on_unless_switched_off(monkeypatch):
    assert songgate.enabled() is False, "the tests run it off (conftest)"
    monkeypatch.delenv("ANCHOR_SONG_GATE")
    assert songgate.enabled() is True


def _wav(path: Path, audio: np.ndarray) -> Path:
    write_wav(path, audio)
    return path


def test_dead_air_after_the_music_is_cut(tmp_path):
    """Lucid Tremor (2026-10-27-4) ended in 5.7 s of silence, Catapult Hammer in 3.4 s."""
    music = synth_techno(12.0, 165, 3)
    f = _wav(tmp_path / "padded.wav", np.vstack([music, np.zeros((6 * SR, 2))]))
    cut = trim_tail(f)
    assert 5.0 < cut < 6.0
    left = decode(f)
    assert abs(len(left) / SR - 12.4) < 0.3, "the music and 0.4 s after it stay"
    assert np.abs(left[-200:]).max() < 1e-3, "and it fades out, no click"


def test_a_track_that_plays_to_the_end_is_left_alone(tmp_path):
    f = _wav(tmp_path / "full.wav", synth_techno(12.0, 165, 4))
    before = f.read_bytes()
    assert trim_tail(f) == 0.0 and f.read_bytes() == before


def _verdict(measures):
    fails = songgate.judge(measures)
    return {"verdict": "FAIL" if fails else "PASS", "measures": measures, "fails": fails}


def _fail(*_, **__):
    return _verdict(dict(SUNO_LIKE, melody_share=0.62))


def _gate_on(monkeypatch):
    """The gate's verdicts come from the test; the fixture engine then counts as a real engine."""
    monkeypatch.setenv("ANCHOR_SONG_GATE", "1")


def test_no_take_passing_holds_the_slot_and_ships_nothing(fast_profile, site_dir, tmp_path, monkeypatch):
    _gate_on(monkeypatch)
    monkeypatch.setattr(pipeline, "gate_take", _fail)
    out = tmp_path / "drop"
    with pytest.raises(pipeline.SongGateHeld) as held:
        pipeline.make(fast_profile, "2026-10-25", out, engine_name="fixture", art_mode="procedural",
                      catalog_path=site_dir / "data" / "catalog.json", retries=1)
    tries = held.value.attempts
    assert [a["attempt"] for a in tries] == [0, 1], "every take the job had time for was tried"
    assert len({a["seed"] for a in tries}) == 2, "each try is a new seed, not the same take again"
    assert all(a["song_gate"]["verdict"] == "FAIL" and not a["ok"] for a in tries)
    assert "too little melody and harmony under the drums" in tries[0]["song_gate"]["fails"][0]
    assert not (out / "meta.json").exists() and not list(out.glob("*.mp4")), "nothing was rendered"


@pytest.mark.slow
def test_the_best_passing_take_ships(fast_profile, site_dir, tmp_path, monkeypatch):
    """Six takes allowed, best of three: the run stops after the third pass and keeps the take
    that sits furthest inside Anchit's songs, not the first one that scraped through."""
    _gate_on(monkeypatch)
    monkeypatch.setenv("ANCHOR_TAKES", "6")
    monkeypatch.setenv("ANCHOR_BEST_OF", "3")
    verdicts = iter([_fail(),                                                      # take 1 fails
                     _verdict(dict(SUNO_LIKE, melody_share=0.80)),                 # take 2 scrapes through
                     _verdict(dict(SUNO_LIKE, melody_share=0.91, section_changes=15)),   # take 3 is the best
                     _verdict(SUNO_LIKE)])                                         # take 4 passes; that is three
    monkeypatch.setattr(pipeline, "gate_take", lambda *a, **k: next(verdicts))
    meta = pipeline.make(fast_profile, "2026-10-25", tmp_path / "d", engine_name="fixture", art_mode="procedural",
                         catalog_path=site_dir / "data" / "catalog.json")
    tries = meta["qc"]["attempts"]
    assert sorted(a["attempt"] for a in tries) == [0, 1, 2, 3], "stopped after the third pass"
    assert tries[-1]["attempt"] == 2 and tries[-1]["chosen"], "the shipped take is the best, and last in the log"
    assert sum(a["chosen"] for a in tries) == 1
    assert meta["brief"]["seed"] == tries[-1]["seed"]
    assert (tmp_path / "d" / "master.wav").exists()


def test_no_new_take_starts_that_would_run_past_the_jobs_limit(fast_profile, site_dir, tmp_path, monkeypatch):
    _gate_on(monkeypatch)
    monkeypatch.setattr(pipeline, "gate_take", _fail)
    with pytest.raises(pipeline.SongGateHeld) as held:
        pipeline.make(fast_profile, "2026-10-25", tmp_path / "d", engine_name="fixture", art_mode="procedural",
                      catalog_path=site_dir / "data" / "catalog.json", retries=4, deadline=time.time() + 60)
    assert len(held.value.attempts) == 1
    assert pipeline.time_for_another_take(None, [9999.0]) is True
    assert pipeline.time_for_another_take(time.time() + 3 * 3600, [3600.0]) is True
    assert pipeline.time_for_another_take(time.time() + 3600, [3600.0]) is False


def test_a_held_slot_gets_new_seeds_in_the_next_run(fast_profile, site_dir, tmp_path, monkeypatch):
    """The engine is seeded by the drop id: without a salt the next run would render the same
    failing takes again. Each run salts the seeds with its own id."""
    _gate_on(monkeypatch)
    monkeypatch.setattr(pipeline, "gate_take", _fail)
    seeds = {}
    for salt in ("", "4001", "4002"):
        monkeypatch.setenv("ANCHOR_SEED_SALT", salt)
        with pytest.raises(pipeline.SongGateHeld) as held:
            pipeline.make(fast_profile, "2026-10-25", tmp_path / f"d{salt}", engine_name="fixture",
                          art_mode="procedural", catalog_path=site_dir / "data" / "catalog.json", retries=0)
        seeds[salt] = held.value.attempts[0]["seed"]
    assert len(set(seeds.values())) == 3


@pytest.mark.slow
def test_a_queued_suno_song_gets_the_gate_as_a_note(fast_profile, site_dir, tmp_path, monkeypatch):
    """Anchit's own Suno songs set the gate's limits, so the gate never holds one back; a miss is
    written on the drop as a warning."""
    _gate_on(monkeypatch)
    q = tmp_path / "queue"
    q.mkdir()
    _wav(q / "05_neon-bounce.wav", synth_techno(30.0, 165, 5))
    asked = []
    monkeypatch.setattr(pipeline, "gate_take", lambda m, engine=None: asked.append(engine) or _fail())
    monkeypatch.setattr(pipeline, "autofill", lambda *a, **k: None)
    meta = pipeline.make(fast_profile, "2026-10-25", tmp_path / "d", art_mode="procedural",
                         catalog_path=site_dir / "data" / "catalog.json", queue_dir=q)
    assert asked == ["queue"]
    first = meta["qc"]["attempts"][0]
    assert first["song_gate"]["verdict"] == "FAIL" and any(w.startswith("song gate:") for w in first["warn"])


def test_make_on_the_command_line_exits_3_and_writes_why(tmp_path, monkeypatch):
    from anchor import __main__ as cli

    def held(*a, **k):
        raise pipeline.SongGateHeld("no take passed the song gate in 2 takes",
                                    [{"attempt": 0, "song_gate": {"verdict": "FAIL", "fails": ["ends in dead air (silent_tail_s 4.2 s, limit 3.0)"]}}])
    monkeypatch.setattr(pipeline, "make", held)
    out = tmp_path / "build" / "2026-10-25-2"
    assert cli.main(["make", "--date", "2026-10-25-2", "--out", str(out)]) == 3
    note = json.loads((out / "held.json").read_text())
    assert note["id"] == "2026-10-25-2" and note["reason"].startswith("no take passed")
    assert note["why"] == ["ends in dead air (silent_tail_s 4.2 s, limit 3.0)"]


def test_the_mac_renders_the_big_model_and_the_cpu_keeps_the_small_one(fast_profile, monkeypatch):
    music = fast_profile.music
    mac, cpu, plain = renderer_settings(music, "mac"), renderer_settings(music, "cpu"), renderer_settings(music, "")
    assert mac["dit_model"] == "acestep-v15-xl-sftturbo50-Q8_0" and mac["lm_model"] == "acestep-5Hz-lm-4B-Q8_0"
    assert mac["steps"] == 8 and mac["takes"] == 6 and mac["best_of"] == 2
    assert cpu["dit_model"] == plain["dit_model"] == "acestep-v15-sft-Q8_0" and cpu["best_of"] == 1
    with pytest.raises(ValueError):
        renderer_settings(music, "gpu-cluster")
    monkeypatch.setenv("ANCHOR_RENDERER", "mac")
    assert pipeline.take_plan(fast_profile, retries=1) == (6, 2)
    from anchor.music import one_engine
    eng = one_engine(music, "acestep_cpp")
    assert eng.dit_model == "acestep-v15-xl-sftturbo50-Q8_0.gguf" and eng.steps == 8 and eng.shift == 3.0


def test_the_workflow_picks_the_mac_only_when_it_is_awake():
    text = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "daily.yml").read_text()
    assert "runs-on: ${{ fromJSON(needs.plan.outputs.runs_on) }}" in text
    assert '"self-hosted","macOS","ARM64","anchor-mac"' in text and "ANCHOR_MAC_SEEN" in text
    assert "mac-watch:" in text and "gh run cancel" in text and "-f renderer=cpu" in text
    assert 'if [ "$RC" = 3 ]' in text and text.count("steps.make.outputs.held != 'true'") == 3
    assert "ANCHOR_SEED_SALT: ${{ github.run_id }}" in text and "requirements-gate.txt" in text
    assert "acestep-v15-xl-sftturbo50-Q8_0.gguf:5305828768" in text, "the Mac's DiT, with its byte size from the model repo"
    make = text.split("\n  make:\n", 1)[1].split("\n  pages:\n", 1)[0]
    assert "if: env.ANCHOR_RENDERER != 'mac'\n        with:\n          python-version" in make, "setup-python only off the Mac"
    assert "/opt/homebrew/bin/python3.12" in make and 'echo "$VENV/bin" >> "$GITHUB_PATH"' in make


def test_the_mac_setup_script_only_lets_the_daily_workflow_on_main_use_the_mac():
    import subprocess
    root = Path(__file__).resolve().parent.parent
    script = (root / "scripts" / "mac-runner-setup.sh").read_text()
    assert subprocess.run(["bash", "-n", str(root / "scripts" / "mac-runner-setup.sh")]).returncode == 0
    assert "restricted_to_workflows=true" in script and ".github/workflows/daily.yml@refs/heads/main" in script
    assert "ANCHOR_MAC_SEEN" in script and "--remove" in script and "--labels \"anchor-mac\"" in script


@pytest.mark.slow
def test_the_gate_measures_a_static_loop_as_not_a_song(tmp_path):
    """The real measure (librosa): a 40 s synthetic loop with no sections is not a song."""
    f = _wav(tmp_path / "loop.wav", synth_techno(40.0, 165, 7))
    r = songgate.check(f)
    assert r["verdict"] == "FAIL" and set(r["measures"]) >= set(songgate.CHECKS)
    assert any(x["check"] in ("section_changes", "melody_share", "most_different_parts") for x in r["fails"])


def test_the_master_resamples_without_soxr_on_an_ffmpeg_that_lacks_it(monkeypatch):
    """Homebrew's ffmpeg on the Mac renderer has no soxr; the master asked for it and failed."""
    import subprocess as sp
    from anchor import audio
    monkeypatch.setattr(audio, "_RESAMPLER", None)
    monkeypatch.setattr(audio.subprocess, "run", lambda *a, **k: sp.CompletedProcess(a, 1, b"", b"unavailable"))
    assert audio.resampler().startswith("resampler=swr")
    monkeypatch.setattr(audio, "_RESAMPLER", None)
    monkeypatch.setattr(audio.subprocess, "run", lambda *a, **k: sp.CompletedProcess(a, 0, b"", b""))
    assert audio.resampler() == "resampler=soxr"


def test_a_title_the_singer_cannot_say_is_replaced_on_the_next_take(fast_profile, site_dir, tmp_path, monkeypatch):
    """2026-10-31 dry run on the Mac: "Bolts And Boogie" was heard as boats, balls, bold on all
    four takes; the run then failed instead of holding the slot."""
    from anchor import lyriccheck
    monkeypatch.setenv("ANCHOR_SONG_GATE", "1")
    monkeypatch.setattr(lyriccheck, "enabled", lambda: True)
    titles = []

    def check(raw, sheet, title):
        titles.append(title)
        return {"heard": "x", "notes": [], "misheard": [title.split()[0].lower()], "checked": True}
    monkeypatch.setattr(lyriccheck, "check", check)

    class Engine(FixtureEngine):
        name = "acestep_cpp"

        def generate(self, brief, out_dir):
            wav, stats = super().generate(brief, out_dir)
            return wav, {**stats, "engine": "acestep_cpp"}
    monkeypatch.setattr(pipeline, "get_engine", lambda *a, **k: Engine())
    with pytest.raises(pipeline.SongGateHeld) as held:
        pipeline.make(fast_profile, "2026-10-31", tmp_path / "d", art_mode="procedural",
                      catalog_path=site_dir / "data" / "catalog.json", use_queue=False, retries=2)
    assert len(titles) == 3 and len(set(titles)) == 3, titles
    assert all("title sung wrong" in a["fail"][-1] for a in held.value.attempts), "held, not a red run"
