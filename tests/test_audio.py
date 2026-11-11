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


def test_beat_phase_finds_the_grid():
    """The Short pulses on the beat, so the estimator must find where the beats actually are."""
    from anchor import audio

    sr, bpm = audio.SR, 152.0
    beat = 60 / bpm
    for true_off in (0.05, 0.21, 0.33):
        t = np.arange(0, 10, 1 / sr)
        x = np.zeros_like(t)
        hit = np.exp(-np.linspace(0, 7, int(0.03 * sr))) * np.sin(2 * np.pi * 55 * np.linspace(0, 0.03, int(0.03 * sr)))
        for k in range(int(9 / beat)):
            i = int((true_off + k * beat) * sr)
            x[i:i + len(hit)] += hit
        est = audio.beat_phase(x, bpm, sr)
        miss = min(abs(est - true_off), beat - abs(est - true_off))
        assert miss < 0.02, f"phase off by {miss * 1000:.0f} ms (est {est}, true {true_off})"



def test_tempo_is_read_right_across_160_to_200_bpm():
    """The channel now runs 160-200 BPM; the estimate must land on the real tempo, not half or a guess."""
    for bpm in (160, 172, 185, 199, 200):
        est = analyze(synth_techno(40, bpm, 3))["bpm_est"]
        assert est is not None and abs(est - bpm) <= 0.5, (bpm, est)


def test_a_take_far_slower_than_asked_is_made_again():
    """Anchit, 2026-11-10: hard tech has a high BPM; a 150 BPM take for a 168 BPM song fails."""
    base = {"finite": True, "duration_s": 30.0, "rms_db": -12.0, "longest_dropout_s": 0.0,
            "low_ratio": 0.3, "clip_ratio": 0.0}
    ok, fails, _ = quality_gate({**base, "bpm_est": 150.0}, {"duration_s": 30, "bpm": 168})
    assert not ok and fails[0].startswith("too slow: landed at 150.0 BPM, asked 168")
    ok, _, warns = quality_gate({**base, "bpm_est": 161.0}, {"duration_s": 30, "bpm": 168})
    assert ok and warns, "a few BPM off is a note, not a failure"
    ok, _, _ = quality_gate({**base, "bpm_est": 84.0}, {"duration_s": 30, "bpm": 168})
    assert ok, "half time reads as the same tempo"
