"""Scene videos: where the song changes, the cuts, the looks, the caption and the render."""
import subprocess

import numpy as np

from anchor import lyrics as L, scenes as SC, structure, viz
from anchor.util import run

SR = 48_000


def _track(bpm=150.0, plan=(("quiet", 8), ("loud", 16), ("quiet", 8), ("loud", 16), ("quiet", 4))):
    """Kicks on the beat: loud sections have a kick and bass, quiet ones only a soft hat."""
    beat = 60.0 / bpm
    out = []
    t = np.arange(int(beat * SR)) / SR
    kick = np.sin(2 * np.pi * (55 + 90 * np.exp(-t * 30)) * t) * np.exp(-t * 9)
    hat = np.random.default_rng(1).standard_normal(len(t)) * np.exp(-t * 60) * 0.05
    for kind, bars in plan:
        for _ in range(bars * 4):
            out.append(kick * 0.9 if kind == "loud" else hat)
    return np.concatenate(out).astype(np.float32), beat


def test_sections_find_the_drops_and_cut_on_the_bar_line():
    audio, beat = _track()
    secs = structure.sections(audio, 150.0, 0.0)
    kinds = [s["kind"] for s in secs]
    assert kinds[0] == "intro" and kinds[-1] == "outro" and kinds.count("drop") >= 2
    assert any(k in ("breakdown", "build") for k in kinds[1:-1])
    bar = 4 * beat
    for a, b in zip(secs, secs[1:]):
        assert a["end"] == b["start"]                                  # no gaps, no overlaps
        assert abs(a["end"] / bar - round(a["end"] / bar)) < 0.02      # every cut is on a bar line
    assert secs[0]["start"] == 0.0 and abs(secs[-1]["end"] - len(audio) / SR) < 0.01
    assert all(s["end"] - s["start"] >= 4 * bar * 0.99 for s in secs)  # never shorter than 4 bars


def test_a_long_drop_is_cut_at_phrase_length_and_neighbours_look_different():
    audio, _ = _track(plan=(("quiet", 8), ("loud", 40), ("quiet", 4)))
    secs = structure.sections(audio, 150.0, 0.0)
    assert sum(1 for s in secs if s["kind"] == "drop") >= 3
    looks = SC.assign_looks(secs)
    assert all(a != b for a, b in zip(looks, looks[1:]))


def test_scene_frames_are_contiguous_and_cover_the_song():
    secs = [{"start": 0.0, "end": 3.3}, {"start": 3.3, "end": 9.7}, {"start": 9.7, "end": 20.0}]
    fr = SC.frames(secs, 20.0)
    assert fr[0][0] == 0 and fr[-1][1] == 600
    assert all(a[1] == b[0] for a, b in zip(fr, fr[1:]))


def test_spectrum_levels_are_per_band_and_bounded():
    audio, _ = _track()
    lv = viz.band_levels(audio, 30, int(len(audio) / SR * 30))
    assert lv.shape[1] == viz.BANDS and 0.0 <= lv.min() and lv.max() <= 1.0
    raw = viz.draw(lv[100], 640, 200, (10, 200, 250), big=False)
    assert len(raw) == 640 * 200 * 4


def test_caption_has_one_sung_line_at_a_time_and_a_tag_per_scene(tmp_path):
    words = [(w, 5 + i * 0.4, 5 + i * 0.4 + 0.3) for i, w in enumerate("we break the cage lost in the sound".split())]
    lines = L.to_lines(words, max_chars=20)
    secs = [{"start": 0.0, "end": 4.0, "kind": "intro", "variant": 0, "bars": 4},
            {"start": 4.0, "end": 12.0, "kind": "drop", "variant": 0, "bars": 8}]
    path = SC.write_ass(tmp_path / "s.ass", "#6ff6ff", 1920, 1080, secs, lines, "Cold Bunker", "Techno 155 BPM")
    text = path.read_text()
    caps = [ln for ln in text.splitlines() if ",Cap," in ln]
    assert len(caps) == len(lines) and all("\\kf" in c for c in caps)
    assert "COLD BUNKER" in text and "// DROP 01" in text


def test_scene_video_renders_both_shapes_at_the_audio_length(tmp_path):
    audio = tmp_path / "tone.mp3"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=110:d=8", "-c:a", "libmp3lame", audio])
    art = tmp_path / "art.jpg"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1080x1080:d=1", "-frames:v", "1", art])
    secs = [{"start": 0.0, "end": 2.0, "kind": "intro", "variant": 0, "bars": 1},
            {"start": 2.0, "end": 3.6, "kind": "build", "variant": 0, "bars": 1},
            {"start": 3.6, "end": 5.2, "kind": "drop", "variant": 0, "bars": 1},
            {"start": 5.2, "end": 6.4, "kind": "drop", "variant": 1, "bars": 1},
            {"start": 6.4, "end": 8.0, "kind": "breakdown", "variant": 0, "bars": 1}]
    lines = L.to_lines([("we", 2.5, 2.8), ("break", 2.9, 3.2), ("the", 3.3, 3.5), ("cage", 3.6, 4.0)])
    for vertical, size in ((False, (1920, 1080)), (True, (1080, 1920))):
        out = tmp_path / f"v{vertical}.mp4"
        info = SC.render_scene_video(SC.square(art, tmp_path / "t.jpg"), audio, out, "#6ff6ff", secs, "Still Spinning",
                                     "Techno 150 BPM", tmp_path / f"w{vertical}", bpm=150.0, beat_offset=0.0,
                                     lines=lines, vertical=vertical)
        assert (info["width"], info["height"]) == size and abs(info["duration"] - 8.0) < 0.2 and info["scenes"] == 5
        assert subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-f", "null", "-"],
                              capture_output=True).stderr == b""


def test_title_sits_at_the_top_when_lyrics_are_shown(tmp_path):
    """The caption lives low in the frame; the title must not sit on it or on the card."""
    import re
    from anchor import scenes
    secs = [{"start": 0.0, "end": 20.0, "kind": "intro", "variant": 0, "bars": 8}]
    lines = [{"start": 1.0, "end": 3.0, "words": [("hello", 1.0, 1.5), ("world", 1.6, 2.0)]}]
    for W, H in ((1920, 1080), (1080, 1920)):
        ass = scenes.write_ass(tmp_path / "a.ass", "#e8582f", W, H, secs, lines, "Kindness Needs Truth", "Slow Techno 95 BPM").read_text()
        ys = [int(m) for m in re.findall(r"Title,,0,0,0,,\{\\pos\(\d+,(\d+)\)", ass)]
        assert ys and all(y < 0.2 * H for y in ys), (W, H, ys)
