"""Drums under the lead and chords (anchor.mixbalance, 2026-10-31)."""
import math
import wave
from pathlib import Path

import numpy as np
import pytest

from anchor import mixbalance
from anchor.config import load_profile


def test_the_cut_puts_the_held_part_at_the_target():
    cut = mixbalance.cut_for(0.649, 0.84)
    g2 = 10 ** (-cut / 10)
    assert abs(0.649 / (0.649 + 0.351 * g2) - 0.84) < 1e-9
    assert 4.0 < cut < 5.5


def test_a_take_already_there_is_left_alone():
    assert mixbalance.cut_for(0.85, 0.84) == 0.0
    assert mixbalance.cut_for(0.0, 0.84) == 0.0


def test_the_profile_aims_inside_the_suno_range_and_caps_the_cut():
    music = load_profile().music
    assert 0.7937 < float(music["melody_target"]) <= 0.918
    assert 0 < float(music["max_drum_cut_db"]) <= 6.0


def _write(path: Path, y: np.ndarray, sr: int) -> None:
    pcm = (np.clip(y, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.stack([pcm, pcm], 1).tobytes())


def test_drums_come_down_and_the_melody_share_goes_up(tmp_path):
    pytest.importorskip("librosa")
    sr, secs = 22050, 30
    t = np.arange(sr * secs) / sr
    pad = 0.12 * (np.sin(2 * math.pi * 220 * t) + np.sin(2 * math.pi * 330 * t))
    kick = np.zeros_like(t)
    rng = np.random.default_rng(1)
    for start in np.arange(0, secs, 0.4):                    # 150 bpm hits
        i = int(start * sr)
        n = min(len(t) - i, 2000)
        kick[i:i + n] += 0.9 * rng.standard_normal(n) * np.exp(-np.arange(n) / 300)
    src, dst = tmp_path / "take.wav", tmp_path / "balanced.wav"
    _write(src, 0.6 * (pad + kick), sr)
    info = mixbalance.balance(src, dst, target=0.84, max_cut_db=6.0)
    assert info["before"] < 0.84
    assert info["after"] > info["before"] + 0.05
    assert 0 < info["drum_cut_db"] <= 6.0
    with wave.open(str(dst)) as w:
        assert w.getnframes() == sr * secs and w.getnchannels() == 2
