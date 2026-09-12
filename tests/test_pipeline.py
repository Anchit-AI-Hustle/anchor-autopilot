import json

from anchor import pipeline
from anchor.util import read_json


def test_full_drop_cycle_site_only(fast_profile, site_dir, tmp_path, monkeypatch):
    monkeypatch.delenv("CF_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("BUFFER_API_KEY", raising=False)
    cat_path, status_path = site_dir / "data" / "catalog.json", site_dir / "data" / "status.json"

    day1 = tmp_path / "d1"
    meta = pipeline.make(fast_profile, "2026-09-11", day1, engine_name="fixture", art_mode="procedural",
                         catalog_path=cat_path)
    files = meta["files"]
    for key in ("mp3", "flac", "short", "cover"):
        assert (day1 / files[key]).exists(), key
    assert files["short"].startswith("ANCHOR-2026-09-11-") and files["short"].endswith("-short.mp4")
    assert meta["video"]["width"] == 1080 and meta["video"]["height"] == 1920
    assert abs(meta["loudness"]["after"]["input_i"] - fast_profile.music["loudness_lufs"]) <= 1.0

    pub = pipeline.publish(fast_profile, day1, "https://example.com/v.mp4", site_only=True)
    assert pub["status"] == "released"
    assert pub["payload"]["metadata"]["youtube"]["isAiGenerated"] is True

    drop = pipeline.record(fast_profile, day1, repo="Anchit-AI-Hustle/anchor-autopilot",
                           short_url="https://example.com/v.mp4", catalog_path=cat_path,
                           status_path=status_path, site_dir=site_dir)
    assert drop["status"] == "released"
    assert drop["audio_url"].endswith(f"/releases/download/drop-2026-09-11/{files['mp3']}")
    assert (site_dir / drop["cover"]).exists() and (site_dir / "og.jpg").exists()
    status = read_json(status_path)
    assert status["last_run"]["result"] == "ok" and status["next_post_at"] == "2026-09-12T17:30:00Z"
    assert status["streak"] == 1

    day2 = tmp_path / "d2"
    meta2 = pipeline.make(fast_profile, "2026-09-12", day2, engine_name="fixture", art_mode="procedural",
                          catalog_path=cat_path)
    assert meta2["brief"]["lane"] != meta["brief"]["lane"]
    assert meta2["brief"]["title"] != meta["brief"]["title"]
    pipeline.publish(fast_profile, day2, "https://example.com/v2.mp4", site_only=True)
    pipeline.record(fast_profile, day2, repo="Anchit-AI-Hustle/anchor-autopilot", catalog_path=cat_path,
                    status_path=status_path, site_dir=site_dir)
    cat = json.loads(cat_path.read_text())
    assert [d["id"] for d in cat["drops"]] == ["2026-09-12", "2026-09-11"], "newest first"
    assert cat["legacy"], "legacy releases survive catalog updates"
    assert read_json(status_path)["streak"] == 2
    assert pipeline.sync(fast_profile, catalog_path=cat_path) == 0  # no Buffer key -> skipped


def test_measured_tempo_overrides_requested_bpm(fast_profile, site_dir, tmp_path, monkeypatch):
    import anchor.pipeline as pl
    from anchor.music import FixtureEngine, synth_techno, write_wav

    class OffTempo(FixtureEngine):
        def generate(self, brief, out_dir):
            out_dir.mkdir(parents=True, exist_ok=True)
            wav = out_dir / "off.wav"
            write_wav(wav, synth_techno(float(brief["duration_s"]), 150, 9))  # model "chose" 150
            return wav, {"engine": "fixture", "total_s": 0.0}
    monkeypatch.setattr(pl, "get_engine", lambda *a, **k: OffTempo())
    brief = pl.make_brief(fast_profile, "2026-09-23", [])
    assert abs(brief["bpm"] - 150) > 1, "pick a date whose brief asks for a tempo other than 150"
    meta = pl.make(fast_profile, "2026-09-23", tmp_path / "d", art_mode="procedural",
                   catalog_path=site_dir / "data" / "catalog.json")
    assert meta["brief"]["bpm"] == 150 and meta["brief"]["bpm_requested"] == brief["bpm"]
    assert "150 BPM" in meta["brief"]["description"] and "hard techno 150 bpm" in meta["brief"]["tags"]


def test_dry_run_publish_never_calls_buffer(fast_profile, tmp_path, monkeypatch, site_dir):
    import anchor.publish as pub_mod

    def forbidden(*a, **k):
        raise AssertionError("network call during dry run")
    monkeypatch.setattr(pub_mod.urllib.request, "urlopen", forbidden)
    d = tmp_path / "d"
    pipeline.make(fast_profile, "2026-09-20", d, engine_name="fixture", art_mode="procedural",
                  catalog_path=site_dir / "data" / "catalog.json")
    res = pipeline.publish(fast_profile, d, "https://example.com/v.mp4", dry_run=True)
    assert res["status"] == "dry-run"


def test_failure_status(tmp_path):
    path = tmp_path / "status.json"
    pipeline.fail("make", "ace-synth crashed", "https://github.com/x/y/actions/runs/1", status_path=path)
    st = read_json(path)
    assert st["last_run"]["result"] == "failed" and st["last_run"]["stage"] == "make"


def test_buffer_failure_still_releases_on_site(fast_profile, site_dir, tmp_path, monkeypatch):
    import pytest
    import anchor.pipeline as pl
    from anchor.publish import BufferError

    monkeypatch.setenv("BUFFER_API_KEY", "k")

    def not_servable(*a, **k):
        raise BufferError("media URL never became servable")
    monkeypatch.setattr(pl, "verify_media_url", not_servable)
    cat_path, status_path = site_dir / "data" / "catalog.json", site_dir / "data" / "status.json"
    d = tmp_path / "d"
    pipeline.make(fast_profile, "2026-09-21", d, engine_name="fixture", art_mode="procedural", catalog_path=cat_path)
    with pytest.raises(BufferError):
        pipeline.publish(fast_profile, d, "https://example.com/v.mp4")
    assert read_json(d / "publish.json")["status"] == "error"
    drop = pipeline.record(fast_profile, d, repo="o/r", catalog_path=cat_path, status_path=status_path,
                           site_dir=site_dir)
    assert drop["status"] == "error" and "servable" in drop["error"]


def test_engine_paths_are_absolute(monkeypatch, tmp_path):
    """The engine runs with cwd set to the drop folder, so its paths must be absolute."""
    from anchor import music

    monkeypatch.chdir(tmp_path)
    (tmp_path / "vendor/acestep.cpp/build").mkdir(parents=True)
    monkeypatch.setenv("ACESTEP_BIN", "vendor/acestep.cpp/build")
    monkeypatch.setenv("ACESTEP_MODELS", "vendor/models")
    engine = music.get_engine({"engine": "acestep_cpp", "dit_model": "dit", "lm_model": "lm"})
    assert engine.bin_dir.is_absolute() and engine.models_dir.is_absolute()
    assert engine.bin_dir == (tmp_path / "vendor/acestep.cpp/build").resolve()
