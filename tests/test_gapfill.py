"""A short dropout is mended with the bar before it; the space between kicks is not a hole.

2026-11-21: every take of Sky Belongs To Nobody was held, nothing posted. The raw takes had no
dead air at all; the 16-bit master turned the space between the kicks of a sparse intro into
"holes" of 20 to 50 ms, and the takes that did have a real gap had one of 0.3 to 0.8 s that one
bar of the groove fills."""
import numpy as np
import pytest

pytest.importorskip("scipy")   # the song gate's own dependency (requirements-gate.txt)

from anchor import gapfill, songgate  # noqa: E402

SR = 22050
BPM = 170.0


def loop(seconds: float, sparse: bool = False) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    beat = 60.0 / BPM
    phase = (t % beat) / beat
    kick = np.sin(2 * np.pi * 55 * t) * np.exp(-phase * 18)
    y = 0.6 * kick
    if sparse:
        y = np.where(phase < 0.45, y, 0.0)            # kick only: dead air between the hits
    else:
        y += 0.2 * np.sin(2 * np.pi * 220 * t)         # a pad that never stops
    return np.stack([y, y], axis=1)


def test_a_short_gap_is_filled_from_the_bar_before():
    y = loop(60)
    a = int(30 * SR)
    y[a:a + int(0.5 * SR)] = 0.0
    assert songgate.holes_and_breaks(y.mean(axis=1), SR)[0] == 1
    fixed, done = gapfill.mend(y, SR, BPM)
    assert len(done) == 1 and abs(done[0][0] - 30) < 0.1
    assert songgate.holes_and_breaks(fixed.mean(axis=1), SR) == (0, 0)


def test_a_gap_longer_than_a_bar_is_left_for_the_gate():
    y = loop(60)
    a = int(30 * SR)
    y[a:a + int(3 * SR)] = 0.0
    fixed, done = gapfill.mend(y, SR, BPM)
    assert done == [] and songgate.holes_and_breaks(fixed.mean(axis=1), SR)[0] == 1


def test_the_space_between_kicks_is_not_a_hole():
    y = loop(60, sparse=True)
    assert songgate.holes_and_breaks(y.mean(axis=1), SR)[0] == 0
    fixed, done = gapfill.mend(y, SR, BPM)
    assert done == [], "a sparse pattern is the music, not a gap to fill"


def test_the_intro_and_the_end_are_never_touched():
    y = loop(60)
    y[int(2 * SR):int(2.5 * SR)] = 0.0
    y[-int(3 * SR):-int(2.5 * SR)] = 0.0
    assert gapfill.mend(y, SR, BPM)[1] == []
