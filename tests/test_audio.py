import numpy as np

from anchor.audio import analyze, best_window, cut, decode, loudness, master, quality_gate
from anchor.music import SR, synth_techno, write_wav


def test_fixture_passes_quality_gate_and_tempo():
    audio = synth_techno(40, 152, 3)
    stats = analyze(audio)
    ok, fails, warns = quality_gate(stats, {"duration_s": 40, "bpm": 152})
    assert ok, fails
    assert abs(stats["duration_s"] - 40) < 0.1
    assert stats["bpm_est"] is not None and abs(stats["bpm_est"] - 152) <= 0.5


def test_gate_catches_silence_and_dropouts():
    silent = np.zeros((SR * 30, 2), dtype=np.float32)
    ok, fails, _ = quality_gate(analyze(silent), {"duration_s": 30, "bpm": 150})
    assert not ok and any("silent" in f for f in fails)
    audio = synth_techno(30, 150, 4)
    audio[SR * 12: SR * 16] = 0
    ok, fails, _ = quality_gate(analyze(audio), {"duration_s": 30, "bpm": 150})
    assert not ok and any("dropout" in f for f in fails)
    ok, fails, _ = quality_gate(analyze(synth_techno(20, 150, 5)), {"duration_s": 30, "bpm": 150})
    assert not ok and any("duration" in f for f in fails)


def test_best_window_is_bar_aligned_and_inside(tmp_path):
    audio = synth_techno(60, 150, 6)
    start, length = best_window(audio, 150, 20)
    bar = 4 * 60 / 150
    assert abs(length / bar - round(length / bar)) < 1e-6
    assert 0 <= start and start + length <= 60
    src = tmp_path / "a.wav"
    write_wav(src, audio)
    dst = tmp_path / "s.wav"
    cut(src, dst, start, length)
    assert abs(len(decode(dst)) / SR - length) < 0.05


def test_master_hits_loudness_target(tmp_path):
    src = tmp_path / "raw.wav"
    write_wav(src, synth_techno(30, 150, 7) * 0.3)
    dst = tmp_path / "master.wav"
    res = master(src, dst, -11.0, -1.0)
    assert abs(res["after"]["input_i"] - (-11.0)) <= 0.5, res
    assert res["after"]["input_tp"] <= -0.9, "true peak must stay under the -1 dBTP target"
    assert abs(loudness(dst)["input_i"] - res["after"]["input_i"]) < 0.01
