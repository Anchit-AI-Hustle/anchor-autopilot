"""More good AI songs reach the channel (2026-11-12: 1 of 29 takes passed)."""
from pathlib import Path

import soundfile as sf

from anchor import lyriccheck, pipeline
from anchor.audio import SR, analyze, decode
from anchor.music import synth_techno


def test_a_title_word_heard_right_and_as_a_variant_is_only_a_note():
    heard = " ".join(["kinetic carbon"] * 9 + ["kinected carbon"] * 4)
    assert lyriccheck.misheard_title(heard, "Kinetic Carbon") == ["kinetic"]
    assert lyriccheck.misheard_title(heard, "Kinetic Carbon", min_exact=0.4) == []


def test_a_title_word_mostly_heard_as_another_word_still_fails():
    heard = " ".join(["boats and boogie"] * 8)
    assert "bolts" in lyriccheck.misheard_title(heard, "Bolts And Boogie", min_exact=0.4)


def test_a_take_that_landed_slow_is_brought_up_to_the_asked_tempo(tmp_path):
    wav = tmp_path / "gen.wav"
    sf.write(wav, synth_techno(30.0, 150, 3), SR)
    stats = analyze(decode(wav))
    brief = {"bpm": 165, "duration_s": 30}
    out, fixed = pipeline.to_tempo(wav, stats, brief, "acestep_cpp")
    assert Path(out) != wav and abs(fixed["bpm_est"] - 165) <= 3
    assert abs(brief["duration_s"] - 30 * 150 / 165) < 1.0


def test_a_take_far_off_or_on_tempo_is_left_alone(tmp_path):
    wav = tmp_path / "gen.wav"
    sf.write(wav, synth_techno(20.0, 150, 3), SR)
    stats = analyze(decode(wav))
    for bpm in (150, 199):
        out, _ = pipeline.to_tempo(wav, stats, {"bpm": bpm, "duration_s": 20}, "acestep_cpp")
        assert out == wav
