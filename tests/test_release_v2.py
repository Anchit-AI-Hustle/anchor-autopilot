"""Every-second-day cadence, Lyria engine plumbing, hook titles, SEO copy, uniqueness gates,
full-length renders and the two-platform publish payload."""
import base64
import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from anchor import pipeline
from anchor.brief import make_brief
from anchor.config import load_profile
from anchor.lyria import LyriaEngine, compose_input, parse_response
from anchor.music import Fallback, FixtureEngine, get_engine
from anchor.publish import build_reel_input
from anchor.seo import description, hook_title, tags, youtube_title
from anchor.unique import audio_similarity, cover_distance, envelope, nearest_cover


# ------------------------------------------------------------------- cadence
def test_release_every_second_day_from_the_anchor_date_across_month_ends():
    p = load_profile()
    assert p.schedule["every_days"] == 2 and p.schedule["anchor_date"] == "2026-09-20"
    on = [d for d in ("2026-09-20", "2026-09-22", "2026-09-30", "2026-10-02", "2026-12-31", "2027-01-02")]
    off = [d for d in ("2026-09-21", "2026-09-23", "2026-10-01", "2027-01-01")]
    assert all(pipeline.is_release_day(p, d) for d in on)
    assert not any(pipeline.is_release_day(p, d) for d in off)
    # daily again when every_days is 1
    daily = load_profile(); daily.raw["schedule"]["every_days"] = 1
    assert all(pipeline.is_release_day(daily, d) for d in on + off)


# --------------------------------------------------------------------- lyria
def test_lyria_prompt_carries_the_nine_layers_and_the_length_in_words():
    p = load_profile()
    b = make_brief(p, "2026-09-22", [])
    text = compose_input(b)
    assert b["caption"] in text and b["lyrics"] in text
    assert "exactly 2:30 (150 seconds)" in text and f"{b['bpm']} BPM" in text and b["key"] in text
    assert "Avoid:" in text and "trance uplift" in text


def test_lyria_response_parser_finds_audio_and_lyrics_wherever_they_are_nested():
    audio = b"ID3fakebytes"
    payload = {"id": "x", "steps": [{"model_output": [
        {"type": "text", "text": "[Verse]\nsteel on steel"},
        {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode()}]}]}
    got, mime, lyrics = parse_response(payload)
    assert got == audio and mime == "audio/mpeg" and lyrics == "[Verse]\nsteel on steel"
    assert parse_response({"steps": []}) == (None, "", "")


def test_lyria_engine_refuses_without_a_key_and_the_registry_falls_back(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(Exception, match="GEMINI_API_KEY"):
        LyriaEngine(api_key="").check()
    p = load_profile()
    eng = get_engine(p.music)                 # profile: lyria with acestep fallback
    assert isinstance(eng, Fallback) and eng.primary.name == "lyria" and eng.secondary.name == "acestep_cpp"
    # the fallback actually runs the second engine when the first cannot start
    fb = Fallback(LyriaEngine(api_key=""), FixtureEngine())
    b = make_brief(p, "2026-09-22", []); b["duration_s"] = 12
    wav, stats = fb.generate(b, Path("build/test-fallback"))
    assert wav.exists() and stats["engine"] == "fixture" and stats["fallback_from"] == "lyria"
    assert "GEMINI_API_KEY" in stats["fallback_reason"]


# ------------------------------------------------------------------- titles
def test_the_hook_names_the_song_when_there_is_one():
    assert hook_title("[Chorus]\nWelcome to project mayhem, welcome to project mayhem\nwelcome to project mayhem") == "Project Mayhem"
    assert hook_title("push it past the limit\nlet the whole place shake\npush it past the limit") == "Push It Past the Limit"
    assert hook_title("this is the beat we are crossing the line\nthis is the beat we are crossing the line") == "Crossing the Line"
    assert hook_title("woo\nwoo\nyeah\nyeah") is None                    # filler is not a title
    assert hook_title("i said\ni said\ni said") is None                  # sung a lot, says nothing
    assert hook_title("only once here") is None and hook_title("") is None and hook_title(None) is None


def test_hook_title_is_used_only_when_it_is_new(monkeypatch, tmp_path):
    """A sung hook overrides the generated title unless a released track already has it."""
    p = load_profile()

    class Sings(FixtureEngine):
        def generate(self, brief, out_dir):
            wav, stats = super().generate(brief, out_dir)
            return wav, {**stats, "lyrics": "[Chorus]\ncold iron sky\ncold iron sky\ncold iron sky"}

    monkeypatch.setattr(pipeline, "get_engine", lambda *a, **k: Sings())
    monkeypatch.setattr(pipeline, "render_full", lambda *a, **k: {"full_169": {"file": "a.mp4", "size_bytes": 1, "duration": 1},
                                                                  "full_916": {"file": "b.mp4", "size_bytes": 1, "duration": 1},
                                                                  "thumbnail": "frame-169.jpg"})
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps({"drops": []}))
    monkeypatch.setattr("anchor.config.CATALOG_PATH", cat)
    p.raw["music"]["duration_s"] = 12
    meta = pipeline.make(p, "2026-09-22", tmp_path / "d", engine_name="fixture", art_mode="procedural",
                         catalog_path=cat, use_queue=False)
    assert meta["brief"]["title"] == "Cold Iron Sky" and meta["brief"]["hook"] == "Cold Iron Sky"
    assert meta["brief"]["youtube_title"].startswith("Cold Iron Sky — ")
    # and not when the hook is already a released title
    cat.write_text(json.dumps({"drops": [{"id": "2026-09-20", "date": "2026-09-20", "title": "Cold Iron Sky",
                                          "lane": "acid", "key": "D minor", "family": "void"}]}))
    meta = pipeline.make(p, "2026-09-24", tmp_path / "e", engine_name="fixture", art_mode="procedural",
                         catalog_path=cat, use_queue=False)
    assert meta["brief"]["title"] != "Cold Iron Sky" and meta["brief"]["hook"] == "Cold Iron Sky"


# ---------------------------------------------------------------------- seo
def test_seo_title_description_and_tags_carry_the_lane_and_tempo():
    p = load_profile()
    b = make_brief(p, "2026-09-22", [])
    lane = p.lane(b["lane"])
    t = youtube_title(b["title"], lane, b["bpm"], "ANCHOR")
    assert t.startswith(b["title"] + " — ") and t.endswith(f"{b['bpm']} BPM") and "ANCHOR" not in t and len(t) <= 60
    assert len(youtube_title("X" * 90, lane, 150, "ANCHOR")) <= 100
    assert youtube_title(b["title"], lane, b["bpm"], "ANCHOR", "for the second you stop thinking") == b["title"] + " — for the second you stop thinking"
    assert youtube_title("X" * 90, lane, 150, "ANCHOR", "a line that would push it over") == "X" * 90 + f" — {lane.genre_line.split(',')[0].strip()}"[:10]
    d = description(p, b)
    head = d.split("\n\n")[0]
    assert head[0].isupper() and head.endswith(".") and "BPM" not in head       # vibe first, specs later
    assert lane.genre_line.split(",")[0] in d and "playlist?list=PLSA3gW62zSYE" in d and "every other day" in d
    ig = description(p, b, "instagram")
    assert "#hardtechno" in ig and "playlist" not in ig and len(ig) <= 2200
    tg = tags(p, lane, b["bpm"])
    assert f"{b['bpm']} bpm techno" in tg and len(tg) == len(set(tg)) and "techno 2026" in tg


# ----------------------------------------------------------------- uniqueness
def _tile(seed: int, size: int = 400) -> Image.Image:
    rs = np.random.default_rng(seed)
    im = Image.new("RGB", (size, size), (10, 10, 10)); d = ImageDraw.Draw(im)
    for _ in range(12):
        x0, y0 = rs.integers(0, size, 2); w, h = rs.integers(20, 200, 2)
        d.rectangle([x0, y0, x0 + w, y0 + h], fill=tuple(int(v) for v in rs.integers(60, 255, 3)))
    return im


def test_cover_distance_separates_reissues_from_new_motifs(tmp_path):
    a, b = _tile(1), _tile(2)
    assert cover_distance(a, a) == 0.0
    assert cover_distance(a, a.resize((200, 200))) < 20          # same art, different size: still the same
    assert cover_distance(a, b) > 84                              # different art: clears the gate
    (tmp_path / "x.jpg").parent.mkdir(exist_ok=True)
    a.save(tmp_path / "2026-09-01.jpg"); b.save(tmp_path / "2026-09-03.jpg")
    dist, who = nearest_cover(a.resize((300, 300)), tmp_path)
    assert who == "2026-09-01" and dist < 20


def test_the_catalogue_near_duplicates_are_caught_and_distinct_covers_pass():
    """The three orange chevron covers already on the site are the reason this gate exists."""
    covers = Path("site/covers")
    assert cover_distance(covers / "2026-09-04.jpg", covers / "2026-09-09.jpg") < 84
    assert cover_distance(covers / "2026-09-04.jpg", covers / "2026-09-12.jpg") > 84


def test_audio_similarity_flags_the_same_record_and_clears_a_different_one():
    sr = 8000; t = np.arange(sr * 20) / sr
    beat = (np.sin(2 * np.pi * 2.5 * t) > 0.9).astype(float)          # 150 BPM kick pattern
    a = beat * np.sin(2 * np.pi * 55 * t)
    a[: sr * 4] *= 0.2                                                  # quiet intro
    same = np.roll(a, sr * 2) * 0.7                                     # same record, shifted and quieter
    other = np.sin(2 * np.pi * 55 * t) * (0.3 + 0.7 * (np.sin(2 * np.pi * t / 7) > 0))   # different arrangement
    ea, es, eo = envelope(a, sr), envelope(same, sr), envelope(other, sr)
    assert audio_similarity(ea, es) > 0.8
    assert audio_similarity(ea, eo) < 0.8


# ------------------------------------------------------------------- publish
def test_reel_input_is_what_buffer_requires_for_instagram():
    inp = build_reel_input("ch1", caption="cap #techno", video_url="https://x/y.mp4", due_at=None, ai_generated=True)
    meta = inp["metadata"]["instagram"]
    assert meta["type"] == "reel" and meta["shouldShareToFeed"] is True and meta["isAiGenerated"] is True
    assert inp["mode"] == "shareNow" and inp["assets"][0]["video"]["url"] == "https://x/y.mp4"
    with pytest.raises(Exception):
        build_reel_input("ch1", caption="c", video_url="http://insecure/y.mp4", due_at=None)


def test_dry_run_publish_writes_both_platform_payloads(tmp_path):
    p = load_profile()
    b = make_brief(p, "2026-09-22", [])
    meta = {"brief": b, "full": {"full_169": {"size_bytes": 10}, "full_916": {"size_bytes": 10}},
            "video": {"size_bytes": 10}}
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    res = pipeline.publish(p, tmp_path, "https://host/a-full-169.mp4", dry_run=True, reel_url="https://host/a-full-916.mp4")
    assert res["payload"]["youtube"]["metadata"]["youtube"]["title"] == b["youtube_title"]
    assert res["payload"]["instagram"]["metadata"]["instagram"]["type"] == "reel"
    assert res["payload"]["instagram"]["text"] == b["caption_instagram"]
    assert json.loads((tmp_path / "publish.json").read_text())["status"] == "dry-run"
