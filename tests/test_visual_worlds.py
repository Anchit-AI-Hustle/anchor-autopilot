"""Different visuals for every song (Anchit, 2026-11-11: "ensure unique different types of visuals
in videos - all have the same style"): each song gets a visual world with its own looks, grade,
finish and overlay, and no world comes back within WORLD_GAP songs."""
import numpy as np

from anchor import fx, scenes

SECS = [{"kind": k, "start": 2.0 * n, "end": 2.0 * n + 2} for n, k in
        enumerate(["intro", "build", "drop", "groove", "breakdown", "outro"])]


def test_every_world_is_its_own_style():
    looks = {w: tuple(scenes.assign_looks(SECS, w)) for w in scenes.WORLDS}
    assert len(set(looks.values())) == len(scenes.WORLDS), "no two worlds cut the same scenes"
    assert set(scenes.WORLDS) == set(fx.STYLES), "every world has its overlay"
    assert len({frozenset(s["draw"]) for s in fx.STYLES.values()}) == len(fx.STYLES)


def test_no_world_comes_back_within_the_gap():
    recent: list[str] = []
    for seed in range(60):
        w = scenes.pick_world(seed * 7919, recent)
        assert w not in recent[-scenes.WORLD_GAP:]
        recent.append(w)
    assert set(recent) == set(scenes.WORLDS), "every world is used"


def test_every_look_builds_a_filter_for_both_shapes():
    for look in {l for w in scenes.WORLDS.values() for ls in w["looks"].values() for l in ls}:
        for W, H in ((1920, 1080), (1080, 1920)):
            lines = scenes._scene(look, 1, W, H, SECS[2], 60, 120, 150.0, 0.0, False, (57, 255, 176))
            assert lines[-1].endswith("[o1]") and any("[y1]" in l for l in lines)


def test_each_overlay_draws_something_different():
    from anchor.audio import SR
    mono = (np.sin(np.arange(SR * 12) * 2 * np.pi * 110 / SR) * (np.arange(SR * 12) % (SR // 2) < 2000)).astype(np.float32)
    frames = {}
    for w in fx.STYLES:
        layer = fx.Layer(320, 180, 150.0, 0.0, (57, 255, 176), SECS, mono, 30, 130, 20, style=w)
        frames[w] = np.frombuffer(layer.frame(75), np.uint8).reshape(90, 160, 4)[..., 3].astype(float)
    names = list(frames)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert np.abs(frames[a] - frames[b]).mean() > 0.5, f"{a} and {b} overlays look the same"
