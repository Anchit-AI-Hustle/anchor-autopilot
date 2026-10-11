from pathlib import Path

from PIL import Image

from anchor import art
from anchor.config import load_profile
from anchor.music import synth_techno, write_wav
from anchor.util import media_summary
from anchor.video import render_short


def test_procedural_cover_for_every_family(tmp_path):
    p = load_profile()
    for i, fam in enumerate(p.families):
        img = art.finish(art.procedural(fam, 100 + i, size=480), "Override Carbon", "ANCHOR", fam, 100 + i, size=480)
        assert img.size == (480, 480) and img.mode == "RGB"
        # not a flat image
        assert len(set(img.resize((32, 32)).tobytes())) > 50


def test_make_cover_falls_back_when_cloudflare_fails(tmp_path, monkeypatch):
    p = load_profile()
    fam = p.family("rust")
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("CF_API_TOKEN", "tok")

    def boom(*a, **k):
        raise RuntimeError("quota")
    monkeypatch.setattr(art, "cloudflare_flux", boom)
    meta = art.make_cover(fam, {"seed": 7, "title": "Null Cipher"}, "ANCHOR", tmp_path, "auto")
    assert meta["source"] == "procedural" and "quota" in meta["fallback_reason"]
    for name, size in (("cover.jpg", 1440), ("cover_1080.jpg", 1080), ("cover_600.jpg", 600)):
        assert Image.open(tmp_path / name).size == (size, size)


def test_og_card(tmp_path):
    p = load_profile()
    fam = p.family("volt")
    img = art.finish(art.procedural(fam, 3, size=600), "Kinetic Relay", "ANCHOR", fam, 3, size=600)
    img.save(tmp_path / "c.jpg")
    art.og_card(tmp_path / "c.jpg", "Kinetic Relay", "Acid Industrial · 150 BPM", fam.accent, tmp_path / "og.jpg")
    assert Image.open(tmp_path / "og.jpg").size == (1200, 630)


def test_render_short_all_viz_types(tmp_path):
    p = load_profile()
    audio = tmp_path / "a.wav"
    write_wav(audio, synth_techno(4, 150, 1))
    brief = {"title": "Override Carbon", "bpm": 150, "key": "F# minor", "lane_name": "Industrial Hard Techno"}
    seen = set()
    for fam in p.families:
        if fam.viz in seen:
            continue
        seen.add(fam.viz)
        cover = tmp_path / f"{fam.id}.jpg"
        art.finish(art.procedural(fam, 5, size=540), brief["title"], "ANCHOR", fam, 5, size=540) \
            .resize((1080, 1080)).save(cover)
        out = tmp_path / f"{fam.id}.mp4"
        info = render_short(cover, audio, out, fam, brief, "ANCHOR", "@AT_ANCHOR", tmp_path / f"w-{fam.id}")
        assert (info["width"], info["height"], info["vcodec"], info["acodec"]) == (1080, 1920, "h264", "aac")
        assert abs(info["duration"] - 4.0) < 0.2 and info["fps"] == 30.0
    assert seen == {"bars", "line", "wave", "scope"}


def test_pulse_peaks_on_the_beat():
    """The cover must be biggest ON the kick - the first version peaked between beats."""
    from anchor import video

    bpm, off, beat = 154, 0.137, 60 / 154
    assert video.pulse_curve(off, bpm, off) == 1.0
    assert video.pulse_curve(off + beat, bpm, off) > 0.99          # every beat, not every other
    assert video.pulse_curve(off + beat / 2, bpm, off) < 0.25      # clearly smaller off-beat
    expr = video.pulse_expr(bpm, off)
    assert "0.1370" in expr and str(video.PULSE_AMP) in expr


def test_cover_chain_can_still_resize_per_frame(fast_profile):
    """format must come BEFORE scale: a trailing format filter freezes the per-frame resize."""
    from anchor import video

    graph = video.build_graph(fast_profile.family("prism"), 150, 30.0,
                              {k: __import__("pathlib").Path(f"/tmp/{k}.txt")
                               for k in ("artist", "title", "meta", "footer")}, 0.2)
    cover = next(part for part in graph.split(";") if part.startswith("[1:v]"))
    assert cover.index("format=rgba") < cover.index("scale="), cover
    assert "eval=frame" in cover and cover.rstrip().endswith("[cov]")


def _frame_169(tmp_path):
    img = Image.new("RGB", (1920, 1080), (8, 16, 30))
    for x in range(0, 1920, 40):                       # something with edges, so a zoom changes pixels
        img.paste((40 + x % 200, 120, 160), (x, 200, x + 20, 800))
    p = tmp_path / "frame.jpg"
    img.save(p, quality=95)
    return p


def test_full_16x9_punches_in_on_the_beat_and_keeps_its_length(tmp_path):
    """Anchit, 2026-10-10: motion graphics for every full video. The frame must move with the kick."""
    import subprocess
    from PIL import ImageChops, ImageStat
    from anchor.video import render_motion
    audio, out = tmp_path / "a.wav", tmp_path / "v.mp4"
    write_wav(audio, synth_techno(5, 120, 3))
    info = render_motion(_frame_169(tmp_path), audio, out, "#d8742f", bpm=120, beat_offset=0.0)
    assert (info["width"], info["height"]) == (1920, 1080) and info["vcodec"] == "h264" and info["acodec"] == "aac"
    assert abs(info["duration"] - 5.0) < 0.3
    got = {}
    for name, t in (("on", 2.0), ("off", 2.3)):         # 120 BPM: a beat every 0.5 s; 2.0 is on it, 2.3 is 0.3 s after
        f = tmp_path / f"{name}.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", str(f)], check=True)
        got[name] = Image.open(f).convert("L")
    bright = {k: ImageStat.Stat(v).mean[0] for k, v in got.items()}
    assert bright["on"] > bright["off"] + 2, bright                       # the flash lands on the beat
    assert ImageStat.Stat(ImageChops.difference(got["on"], got["off"])).mean[0] > 3   # and the zoom moved pixels


def test_full_16x9_without_a_tempo_still_moves_but_does_not_pulse(tmp_path):
    from anchor.video import render_motion
    audio, out = tmp_path / "a.wav", tmp_path / "v.mp4"
    write_wav(audio, synth_techno(3, 120, 4))
    info = render_motion(_frame_169(tmp_path), audio, out, "#d8742f")
    assert (info["width"], info["height"]) == (1920, 1080) and abs(info["duration"] - 3.0) < 0.3


def _stub_full(monkeypatch, tmp_path):
    from anchor import video, scenes
    seen = {"scene": []}
    monkeypatch.setattr(video, "render_short", lambda cover, audio, out, fam, brief, artist, handle, wd, **kw:
                        seen.update(out=out.name, kw=kw) or {"file": out.name})
    monkeypatch.setattr(video, "render_motion", lambda *a, **kw: {"file": "x"})
    monkeypatch.setattr(video, "render_still", lambda *a, **kw: {"file": "s"})
    monkeypatch.setattr(video, "frame_169", lambda *a, **kw: tmp_path / "f.jpg")
    monkeypatch.setattr(video, "frame_916", lambda *a, **kw: tmp_path / "g.jpg")
    monkeypatch.setattr(scenes, "song_sections", lambda *a, **kw: [{"start": 0, "end": 5, "kind": "drop", "variant": 0, "bars": 4}])
    monkeypatch.setattr(scenes, "render_scene_video",
                        lambda tex, audio, out, accent, secs, title, sub, work, **kw: seen["scene"].append((out.name, kw)) or {"duration": 5})
    return seen


def test_full_videos_are_scene_videos_in_both_shapes_when_the_tempo_is_known(tmp_path, monkeypatch):
    from anchor import video
    seen = _stub_full(monkeypatch, tmp_path)
    cover = tmp_path / "c.jpg"
    Image.new("RGB", (64, 64)).save(cover)
    fam = load_profile().families[0]
    lines = [{"start": 1.0, "end": 2.0, "words": [("hi", 1.0, 2.0)]}]
    out = video.render_full(cover, cover, tmp_path / "t.mp3", tmp_path, "base", {"bpm": 150, "title": "T"}, "Techno", "ANCHOR",
                            accent="#fff", fam=fam, cover_1080=cover, handle="@h", beat_offset=0.1, lines=lines)
    names = {n: kw for n, kw in seen["scene"]}
    assert set(names) == {"base-full-169.mp4", "base-full-916.mp4"}
    assert names["base-full-916.mp4"]["vertical"] is True and not names["base-full-169.mp4"].get("vertical")
    assert all(kw["beat_offset"] == 0.1 and kw["lines"] == lines for kw in names.values())
    assert out["scenes"] == 1 and out["lyrics"] == 1 and "out" not in seen


def test_full_9x16_is_the_shorts_design_for_the_whole_track_without_an_accent(tmp_path, monkeypatch):
    from anchor import video
    seen = _stub_full(monkeypatch, tmp_path)
    cover = tmp_path / "c.jpg"
    Image.new("RGB", (64, 64)).save(cover)
    fam = load_profile().families[0]
    video.render_full(cover, cover, tmp_path / "t.mp3", tmp_path, "base", {"bpm": 150, "title": "T"}, "Techno", "ANCHOR",
                      fam=fam, cover_1080=cover, handle="@h", beat_offset=0.1)
    assert seen["out"] == "base-full-916.mp4" and seen["kw"]["beat_offset"] == 0.1
    assert seen["kw"]["maxrate"] == "4M", "a whole track at the Short's 8 Mbit/s is 140 MB; Pages and Instagram fetch it"
    assert not seen["scene"]


def test_motion_lists_every_released_song_newest_first():
    import json
    from anchor import motion
    cat = json.loads((Path(__file__).resolve().parents[1] / "site/data/catalog.json").read_text())
    ids = [d["id"] for d in motion.songs(cat)]
    assert ids == sorted(ids, reverse=True) and len(ids) >= 15
    assert all(d.get("audio_url") for d in motion.songs(cat))
