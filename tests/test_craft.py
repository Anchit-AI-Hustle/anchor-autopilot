"""The craft the channel taught the robot: a take must break down and move; every record is
finished so a phone can hear it; a record already in range is left alone."""
import numpy as np

from anchor import craft
from anchor.music import synth_techno

SR = 48000


def _arranged(seconds=120, bpm=150, drop_at=(50, 66)):
    """A loop with a real breakdown: kick and sub out for 16 s, a filtered high line left."""
    x = synth_techno(seconds, bpm, 3).astype(np.float64)
    t = np.arange(len(x)) / SR
    a, b = int(drop_at[0] * SR), int(drop_at[1] * SR)
    x[a:b] *= 0.08
    hat = 0.05 * np.sin(2 * np.pi * 3000 * t[a:b])[:, None]
    x[a:b] += hat
    # the second half changes character, so the record moves
    x[b:] = x[b:] * 0.8 + 0.1 * np.sin(2 * np.pi * 440 * t[b:])[:, None]
    return x.astype(np.float32)


def test_a_flat_loop_is_sent_back_and_an_arranged_take_passes():
    flat = synth_techno(120, 150, 3)
    fails = craft.gate(craft.measure(flat))
    assert any("no breakdown" in f for f in fails)
    m = craft.measure(_arranged())
    assert [b for b in m["breakdowns"] if b["length"] >= 8] and not any("no breakdown" in f for f in craft.gate(m))


def test_the_finishing_pass_lifts_a_bass_only_mono_record_and_keeps_the_bass_centred():
    t = np.arange(SR * 30) / SR
    sub = 0.8 * np.sin(2 * np.pi * 50 * t) * (np.sin(2 * np.pi * 2.5 * t) > 0)
    rng = np.random.default_rng(1)
    gate = np.sin(2 * np.pi * 2.5 * t) > 0.95
    # a narrow record: identical sub, hats only slightly different left to right
    common = 0.05 * rng.standard_normal(len(t))
    left = sub + (common + 0.01 * rng.standard_normal(len(t))) * gate
    right = sub + (common + 0.01 * rng.standard_normal(len(t))) * gate
    x = np.stack([left, right], axis=1).astype(np.float32)
    out, info = craft.enhance(x)
    assert info["before"]["phone_share"] < 0.1 and info["after"]["phone_share"] > info["before"]["phone_share"] * 1.8
    assert info["after"]["width"] > info["before"]["width"]
    # below 120 Hz the two channels stay identical: the kick and sub are still centred
    lo = lambda ch: np.fft.irfft(np.fft.rfft(ch) * (np.fft.rfftfreq(len(ch), 1 / SR) < 100), len(ch))
    assert np.corrcoef(lo(out[:, 0]), lo(out[:, 1]))[0, 1] > 0.99
    assert np.abs(out).max() <= 0.91 and out.dtype == np.float32


def test_a_record_already_in_range_passes_through_untouched():
    rng = np.random.default_rng(2)
    wide = rng.standard_normal((SR * 20, 2)).astype(np.float32) * 0.1   # broadband and wide: already fine
    out, info = craft.enhance(wide)
    assert info["strength"] == 0.0 and out is wide
