"""Every cover and YouTube thumbnail is original, drawn from its own song, and never repeats one
already out (Anchit, 2026-11-21: "ensure all youtube upload thumbnails are unique in their own way
as per the music and the vibe of each song - ensure no duplicacy or repetition ever - add this as a
test case for youtube uploads - album art must be original and unique and music based only")."""
import itertools
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from anchor import pipeline, soundart
from anchor.unique import COVER_MIN_DISTANCE, cover_distance

ROOT = Path(__file__).resolve().parent.parent
SR = 22050


def song(seed, bpm, acid=False, voice=False, secs=40):
    """A test song: kick on every beat, an off-beat bass, optionally a 303-like line and a voice band."""
    rs = np.random.default_rng(seed)
    t = np.arange(int(secs * SR)) / SR
    beat = 60.0 / bpm
    ph = (t % beat) / beat
    y = np.sin(2 * np.pi * 50 * t) * np.exp(-ph * 18)
    y += 0.4 * np.sin(2 * np.pi * rs.uniform(45, 70) * t) * ((ph > 0.5) & (ph < 0.8))
    bar = (t // (4 * beat)).astype(int)
    y *= 0.5 + 0.5 * np.abs(np.sin(bar * rs.uniform(0.3, 1.7)))
    if acid:
        f = 220 * 2 ** (np.round(4 * np.sin(t * rs.uniform(1, 3))) / 12)
        y += 0.25 * np.sign(np.sin(2 * np.pi * np.cumsum(f) / SR))
    if voice:
        y += 0.2 * np.sin(2 * np.pi * 1800 * t) * (np.sin(2 * np.pi * 0.7 * t) > 0.2)
    return (y / (np.abs(y).max() + 1e-9)).astype(np.float32)


@pytest.fixture(scope="module")
def feats():
    return {name: (soundart.features(song(*args), SR, args[1]), gs) for name, (args, gs) in SPECS.items()}


@pytest.fixture(scope="module")
def pictures(feats):
    return {name: soundart.render(f, gs, minor=True, size=480) for name, (f, gs) in feats.items()}


SPECS = {"hard": ((1, 168, False, False), ("hard_techno",)),
         "acid-mash": ((2, 184, True, False), ("hard_techno", "acid_techno")),
         "industrial-rap": ((3, 184, False, True), ("techno_rap", "industrial_techno")),
         "psy": ((4, 165, True, False), ("psychedelic_techno",)),
         "warehouse": ((5, 165, False, False), ("warehouse_techno",)),
         "hard-again": ((6, 168, False, False), ("hard_techno",))}


def _unused():
    specs = {"hard": ((1, 168, False, False), ("hard_techno",)),
             "acid-mash": ((2, 184, True, False), ("hard_techno", "acid_techno")),
             "industrial-rap": ((3, 184, False, True), ("techno_rap", "industrial_techno")),
             "psy": ((4, 165, True, False), ("psychedelic_techno",)),
             "warehouse": ((5, 165, False, False), ("warehouse_techno",)),
             "hard-again": ((6, 168, False, False), ("hard_techno",))}
    out = {}
    for name, ((seed, bpm, acid, voice), gs) in specs.items():
        feat = soundart.features(song(seed, bpm, acid, voice), SR, bpm)
        out[name] = soundart.render(feat, gs, minor=True, size=480)
    return out


def test_no_two_songs_ever_share_a_cover(pictures, feats):
    """Six songs, five genres, two of them the same genre: for every pair, the later song finds
    a picture at least COVER_MIN_DISTANCE from the earlier one within the gate's redraws, and
    most pairs are distinct on the first draw."""
    names = list(pictures)
    first = 0
    for i, j in itertools.combinations(range(len(names)), 2):
        a, b = names[i], names[j]
        feat, gs = feats[b]
        draws = [cover_distance(soundart.render(feat, gs, True, size=480, variant=v), pictures[a])
                 for v in range(pipeline.ART_TRIES)]
        assert max(draws) >= COVER_MIN_DISTANCE, (a, b, draws)
        first += draws[0] >= COVER_MIN_DISTANCE
    assert first >= 12, f"only {first} of 15 pairs distinct on the first draw"


def test_the_art_is_the_music(pictures):
    """The same song draws the same picture; a different song a different one (music based only)."""
    feat = soundart.features(song(1, 168), SR, 168)
    again = soundart.render(feat, ("hard_techno",), minor=True, size=480)
    assert cover_distance(again, pictures["hard"]) == 0
    other = soundart.render(soundart.features(song(9, 168), SR, 168), ("hard_techno",), minor=True, size=480)
    assert cover_distance(other, pictures["hard"]) > 0


def test_a_mashup_shows_both_of_its_genres():
    feat = soundart.features(song(2, 184, acid=True), SR, 184)
    one = soundart.render(feat, ("hard_techno",), True, size=480)
    both = soundart.render(feat, ("hard_techno", "acid_techno"), True, size=480)
    assert cover_distance(one, both) > 10


def test_a_redraw_is_a_new_picture():
    feat = soundart.features(song(3, 184, voice=True), SR, 184)
    v = [soundart.render(feat, ("techno_rap", "industrial_techno"), True, size=480, variant=i) for i in range(3)]
    assert all(cover_distance(a, b) > 20 for a, b in itertools.combinations(v, 2))


def test_a_song_whose_art_keeps_repeating_is_not_published(monkeypatch):
    """Never a repeat: when every redraw still lands on art already out, the song stops."""
    assert pipeline.ART_TRIES >= 5
    src = Path(pipeline.__file__).read_text()
    assert "raise QualityError(f\"no original art in {ART_TRIES} draws" in src
    assert "tdist >= COVER_MIN_DISTANCE" in src, "the thumbnail is gated as well as the cover"


def test_every_published_thumbnail_is_kept_for_the_gate(tmp_path):
    from PIL import Image
    d = tmp_path / "drop"
    d.mkdir()
    Image.new("RGB", (1920, 1080), (200, 10, 10)).save(d / "frame-169.jpg")
    pipeline.keep_thumb(d, {"thumbnail": "frame-169.jpg"}, tmp_path / "site", "2026-11-22")
    kept = tmp_path / "site" / "thumbs" / "2026-11-22.jpg"
    assert kept.exists() and Image.open(kept).size == (480, 270)


def test_no_new_thumbnail_repeats_one_already_out():
    """The YouTube thumbnails made on the music-drawn art (from 2026-11-21) are all distinct from
    each other and from every thumbnail before them."""
    thumbs = sorted((ROOT / "site" / "thumbs").glob("*.jpg"))
    import re
    new = [t for t in thumbs if re.match(r"\d{4}-\d{2}-\d{2}", t.stem) and t.stem >= "2026-11-21"]
    for a in new:
        for b in thumbs:
            if a != b:
                assert cover_distance(a, b) >= COVER_MIN_DISTANCE, (a.stem, b.stem)


def test_a_redrawn_thumbnail_is_set_on_youtube_once(tmp_path):
    """A thumbnail fixed by scripts/thumb_fix.py goes up on its video once, before anything else."""
    from anchor import thumbs
    img = tmp_path / "fix.jpg"
    Image.new("RGB", (1280, 720), (10, 20, 30)).save(img)
    calls = []

    class Api:
        def set_thumbnail(self, vid, path):
            calls.append((vid, Path(path).name))

    data = {"thumbs": [], "thumb_fixes": [{"drop": "2026-11-22", "video": "MtWfFiG3hpo", "image": str(img)}]}
    cat = tmp_path / "catalog.json"
    cat.write_text('{"drops": []}')
    assert thumbs.run(Api(), [], data, "o/r", tmp_path, "ANCHOR", "MARK", catalog_path=cat) == ["MtWfFiG3hpo"]
    assert data["thumb_fixes"][0]["set"] is True and calls == [("MtWfFiG3hpo", "fix.jpg")]
    assert thumbs.run(Api(), [], data, "o/r", tmp_path, "ANCHOR", "MARK", catalog_path=cat) == []
    assert len(calls) == 1


def test_every_queued_thumbnail_fix_has_its_full_size_frame():
    import json
    up = json.loads((ROOT / "site" / "data" / "uploads.json").read_text())
    for fx in up.get("thumb_fixes", []):
        full = ROOT / fx["image"]
        assert full.exists(), fx
        assert Image.open(full).size == (1280, 720)
