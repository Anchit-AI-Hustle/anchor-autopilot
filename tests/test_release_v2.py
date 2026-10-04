"""Daily cadence, Lyria engine plumbing, hook titles, SEO copy, uniqueness gates,
full-length renders and the three-post publish payload (full track, Short, Reel)."""
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
from anchor.music import Fallback, FixtureEngine, engine_chain, get_engine
from anchor.publish import build_reel_input
from anchor.seo import description, hook_title, tags, youtube_title
from anchor.unique import audio_similarity, cover_distance, envelope, nearest_cover


# ------------------------------------------------------------------- cadence
def test_the_channel_releases_every_day_and_every_second_day_is_one_setting_away():
    p = load_profile()
    assert p.schedule["every_days"] == 1
    on = [d for d in ("2026-09-20", "2026-09-22", "2026-09-30", "2026-10-02", "2026-12-31", "2027-01-02")]
    off = [d for d in ("2026-09-21", "2026-09-23", "2026-10-01", "2027-01-01")]
    assert all(pipeline.is_release_day(p, d) for d in on + off)
    # every second day, counted from the anchor date across month ends
    alt = load_profile(); alt.raw["schedule"]["every_days"] = 2; alt.raw["schedule"]["anchor_date"] = "2026-09-20"
    assert all(pipeline.is_release_day(alt, d) for d in on)
    assert not any(pipeline.is_release_day(alt, d) for d in off)


# --------------------------------------------------------------------- lyria
def test_lyria_prompt_carries_the_nine_layers_and_the_length_in_words():
    p = load_profile()
    b = make_brief(p, "2026-09-22", [])
    text = compose_input(b)
    assert b["caption"] in text and b["lyrics"] in text
    mm, ss = divmod(b["duration_s"], 60)
    assert f"exactly {mm}:{ss:02d} ({b['duration_s']} seconds)" in text and f"{b['bpm']} BPM" in text and b["key"] in text
    assert "Avoid:" in text and "trance uplift" in text


def test_length_and_arrangement_shape_are_drawn_for_the_day_so_records_do_not_share_a_timeline():
    from anchor.music import SHAPES, arrangement
    p = load_profile()
    lo, hi = p.music["duration_range_s"]
    briefs = [make_brief(p, f"2026-10-{d:02d}", []) for d in range(1, 21)]
    lengths, shapes = {b["duration_s"] for b in briefs}, {b["shape"] for b in briefs}
    assert all(lo <= b["duration_s"] <= hi for b in briefs) and len(lengths) > 5 and len(shapes) == len(SHAPES)
    for b in briefs:
        tags = [t for t, _ in arrangement(b["duration_s"], tuple(b["textures"]), b["shape"])]
        assert tags[0] == "intro" and tags[-1] == "outro" and "drop" in tags and "breakdown" in tags
        assert b["lyrics"].count("[") == len(tags)
    # the same day always gets the same record
    assert make_brief(p, "2026-10-03", [])["shape"] == briefs[2]["shape"]
    assert make_brief(p, "2026-10-03", [])["duration_s"] == briefs[2]["duration_s"]


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
    eng = get_engine(p.music)                 # profile: free ACE-Step only (after your Suno songs)
    assert eng.name == "acestep_cpp" and not isinstance(eng, Fallback)
    chain = {**p.music, "engines": ["elevenlabs", "lyria", "acestep_cpp"]}
    assert get_engine(chain, "lyria").secondary.name == "acestep_cpp"   # naming one starts the chain there
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
    assert meta["brief"]["youtube_title"].startswith("Cold Iron Sky | ") and meta["brief"]["youtube_title"].endswith(" | ANCHOR")
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
    # the search phrase rides on the name: "Rupture Pulse | Industrial Hard Techno 154 BPM | ANCHOR"
    assert youtube_title(b["title"], lane, b["bpm"], "ANCHOR") == f"{b['title']} | {lane.genre_line.split(',')[0]} {b['bpm']} BPM | ANCHOR"
    assert youtube_title(b["title"]) == b["title"] and len(youtube_title("X" * 120, lane, 150, "ANCHOR")) <= 100
    assert b["youtube_title"] == youtube_title(b["title"], lane, b["bpm"], "ANCHOR")
    d = description(p, b)
    head, vibe = d.split("\n\n")[:2]
    assert head == f"{lane.genre_line.split(',')[0]} at {b['bpm']} BPM. An ANCHOR original, free download below."   # the search line first
    assert vibe[0].isupper() and vibe.endswith(".") and "BPM" not in vibe                                            # then the vibe
    assert "playlist?list=PLSA3gW62zSYE" in d and "AI use disclosed" in d and len(d) < 700
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


def test_dry_run_publish_writes_the_three_payloads_full_short_and_reel(tmp_path):
    p = load_profile()
    b = make_brief(p, "2026-09-22", [])
    meta = {"brief": b, "full": {"full_169": {"size_bytes": 10}, "full_916": {"size_bytes": 10}},
            "video": {"size_bytes": 10}}
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    res = pipeline.publish(p, tmp_path, "https://host/a-full-169.mp4", dry_run=True,
                           reel_url="https://host/a-full-916.mp4", short_url="https://host/a-short.mp4")
    full, short = res["payload"]["youtube"], res["payload"]["youtube_short"]
    assert full["metadata"]["youtube"]["title"] == b["youtube_title"] == short["metadata"]["youtube"]["title"]
    assert full["assets"][0]["video"]["url"].endswith("full-169.mp4") and short["assets"][0]["video"]["url"].endswith("short.mp4")
    assert full["text"] == b["description"] and short["text"] == b["description_short"] != b["description"]
    # the Short is the preview: shorter words, a pointer to the full track, #shorts, no second notification
    def body(text):   # the record's words: after the search line, before the links
        return text.split("\n\n", 1)[1].split("\n\nFull track:")[0].split("\n\nAll tracks:")[0]
    assert len(body(short["text"])) <= len(body(full["text"])) <= 320
    assert short["text"].split("\n")[0] == full["text"].split("\n")[0]        # the same search line leads both
    assert "Full track: https://www.youtube.com/@AT_ANCHOR/videos" in short["text"] and short["text"].endswith("#shorts")
    assert full["metadata"]["youtube"]["notifySubscribers"] is True and short["metadata"]["youtube"]["notifySubscribers"] is False
    assert full.get("dueAt") == short.get("dueAt") == res["payload"]["instagram"].get("dueAt")
    assert res["payload"]["instagram"]["metadata"]["instagram"]["type"] == "reel"
    assert res["payload"]["instagram"]["text"] == b["caption_instagram"]
    assert json.loads((tmp_path / "publish.json").read_text())["status"] == "dry-run"


def test_the_short_copy_is_the_first_sentence_or_two_of_the_full_copy():
    from anchor.seo import preview_copy
    body = "Warehouse pressure with no off switch. It starts hitting before you're ready. By the end something in you has given way."
    assert preview_copy(body) == "Warehouse pressure with no off switch. It starts hitting before you're ready."
    long_second = "Short first. " + "A second sentence that runs on and on, well past the two lines a phone shows above the fold of a Short, and then keeps going, and going."
    assert len(long_second) > 140
    assert preview_copy(long_second) == "Short first."
    assert preview_copy("One line only.") == "One line only."


def test_an_unconnected_instagram_account_is_a_note_not_a_failed_run(tmp_path, monkeypatch):
    """The YouTube posts are the release; the Reel starts the day the account is connected in Buffer."""
    from anchor.publish import Buffer, BufferError
    p = load_profile()
    b = make_brief(p, "2026-09-22", [])
    meta = {"brief": b, "full": {"full_169": {"size_bytes": 10}, "full_916": {"size_bytes": 10}}, "video": {"size_bytes": 10}}
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    monkeypatch.setenv("BUFFER_API_KEY", "k")
    monkeypatch.setattr(pipeline, "verify_media_url", lambda url, **k: {"url": url, "bytes": 10})
    monkeypatch.setattr(Buffer, "youtube_channel", lambda self, *a: {"id": "yt", "name": "AT_ANCHOR"})
    sent = []
    monkeypatch.setattr(Buffer, "create_short", lambda self, ch, **kw: sent.append(kw) or {"id": f"p{len(sent)}", "status": "buffer"})

    def no_ig(self, *a):
        raise BufferError("no Instagram channel connected in Buffer (connect @anchor_at2803 in Buffer first)")
    monkeypatch.setattr(Buffer, "instagram_channel", no_ig)
    res = pipeline.publish(p, tmp_path, "https://host/full.mp4", short_url="https://host/short.mp4", reel_url="https://host/reel.mp4")
    # Buffer publishes Shorts only: the Short goes out, the full video waits for the channel's own
    # credentials, and neither that nor the missing Instagram account fails the run
    assert [s["video_url"] for s in sent] == ["https://host/short.mp4"]
    assert res["youtube"]["status"] == pipeline.NEEDS_YT and res["youtube"]["error"] is None
    assert res["youtube_short"]["post_id"] == "p1" and res["post_id"] == "p1"
    assert res["instagram"] == {"status": "not connected", "error": None} and res["error"] is None


def test_a_mix_without_the_channel_credentials_waits_instead_of_failing(monkeypatch, tmp_path):
    """A mix is long-form and Buffer publishes Shorts only: nothing is sent, nothing fails."""
    from anchor.publish import Buffer
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BUFFER_API_KEY", "k")
    monkeypatch.setattr(Buffer, "create_short", lambda *a, **k: pytest.fail("a mix must not go through Buffer"))
    (tmp_path / "meta.json").write_text(json.dumps({"date": "2026-09-27", "title": "M", "video": {"size_bytes": 10}}))
    res = pipeline.publish_mix(load_profile(), tmp_path, "https://host/mix.mp4")
    assert res["youtube"]["status"] == pipeline.NEEDS_YT and res["error"] is None
    assert json.loads((tmp_path / "publish.json").read_text())["status"] == pipeline.NEEDS_YT


# ------------------------------------------------------------ allowed sources
PAID_ENGINES = {"elevenlabs", "lyria", "thirdeye"}


def test_songs_come_only_from_free_open_source_engines():
    # Anchit's rule (2026-10-04): free or open-source tools only for music and video.
    chain = engine_chain(load_profile().music)
    assert chain == ["acestep_cpp"]
    assert not PAID_ENGINES & set(chain)


def test_a_day_is_made_from_a_suno_song_or_free_ace_step_and_never_a_paid_key(tmp_path, monkeypatch):
    p = load_profile()
    q = tmp_path / "queue"; q.mkdir()
    cat = tmp_path / "catalog.json"; cat.write_text("{}")
    # Paid keys being present changes nothing: they are never used.
    monkeypatch.setenv("ELEVENLABS_API_KEY", "set")
    monkeypatch.setenv("GEMINI_API_KEY", "set")
    # ACE-Step is built and downloaded later in the same run, so it counts as ready here.
    assert pipeline.can_make(p, q, cat) == (True, "acestep_cpp is ready (free, open source; built in this run)")
    (q / "01-new-song.mp3").write_bytes(b"\0")
    assert pipeline.can_make(p, q, cat) == (True, "a new Suno song is queued")


def test_the_daily_run_never_hands_a_paid_key_to_the_make_step():
    wf = (Path(__file__).parent.parent / ".github/workflows/daily.yml").read_text()
    assert "python -m anchor can-make" in wf
    assert "ELEVENLABS_API_KEY" not in wf and "THIRD_EYE_API_KEY" not in wf and "REPLICATE_API_TOKEN" not in wf
