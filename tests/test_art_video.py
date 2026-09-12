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
