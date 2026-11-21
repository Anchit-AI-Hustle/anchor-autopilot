"""Every visual is a hologram: the art in cyan light on a dark stage, over an emitter, with
scanlines and a flicker in the moving versions. No network; small renders only."""
import numpy as np
from PIL import Image

from anchor import video


def _art(tmp_path):
    img = Image.new("RGB", (600, 600), (40, 40, 40))
    img.paste((230, 90, 40), (150, 150, 450, 450))
    p = tmp_path / "art.jpg"
    img.save(p)
    return p


def test_the_art_becomes_cyan_light_with_a_fringe_and_soft_edges(tmp_path):
    h = np.asarray(video.holo_art(_art(tmp_path), 300, "#ff3b1f")).astype(int)
    assert h.shape == (300, 300, 4)
    centre = h[150, 150]
    assert centre[2] > centre[0] and centre[1] > centre[0]          # cyan, not the art's orange
    assert h[0, 0, 3] < h[150, 150, 3]                              # feathered at the edge


def test_the_169_frame_stands_the_hologram_in_the_songs_own_art(tmp_path):
    """2026-11-21: the stage behind the hologram is the song's own art (dimmed most under the
    title), and the song sets which side the hologram stands on, so no two thumbnails match."""
    for title in ("Crossing The Threshold", "Sky Belongs To Nobody", "Spin Or Fall", "Project Mayhem"):
        brief = {"title": title, "bpm": 150}
        out = video.frame_169(_art(tmp_path), brief, "Industrial Hard Techno", "ANCHOR", tmp_path / "f.jpg", "#ff3b1f")
        a = np.asarray(Image.open(out).convert("RGB")).astype(int)
        assert a.shape == (1080, 1920, 3)
        flip = video.mirror_layout(brief)
        holo = a[200:800, 170:770] if flip else a[200:800, 1150:1750]
        assert holo[..., 2].mean() > holo[..., 0].mean() + 15, title       # cyan projection
        ex = 1920 - 1460 if flip else 1460
        assert a[1000, ex].mean() > 120, title                              # the emitter glows under it
    sides = {video.mirror_layout({"title": t}) for t in ("A", "B", "C", "D", "E", "F", "G", "H")}
    assert sides == {True, False}, "both layouts are used"


def test_the_916_frame_and_the_short_stage_are_holograms_too(tmp_path):
    out = video.frame_916(_art(tmp_path), tmp_path / "v.jpg", "#35c6ff")
    a = np.asarray(Image.open(out).convert("RGB")).astype(int)
    assert a.shape == (1920, 1080, 3) and a[1640, 540].mean() > 150
    video.background(_art(tmp_path), tmp_path / "bg.jpg")
    assert np.asarray(Image.open(tmp_path / "bg.jpg")).mean() < 40


def test_the_moving_versions_carry_scanlines_and_a_flicker():
    graph = video.build_graph(__import__("anchor.config", fromlist=["x"]).load_profile().families[0], 150, 30.0,
                              {k: __import__("pathlib").Path(f"/tmp/{k}.txt") for k in ("artist", "title", "meta", "footer")})
    assert "[3:v]overlay" in graph and "eq=brightness" in graph
    src = open(video.__file__).read()
    assert "scanlines(1920, 1080" in src and src.count("FLICKER") >= 3
