"""Eleven Music: the request the API documents, the refusals it can send back, and the
fallback when there is no key. A fake server stands in; nothing touches the network."""
import io
import json
import subprocess
import urllib.error
from pathlib import Path

import pytest

from anchor import elevenlabs
from anchor.brief import make_brief
from anchor.config import load_profile
from anchor.elevenlabs import ElevenLabsEngine, ElevenLabsError
from anchor.music import Fallback, FixtureEngine


def _brief(seconds=20):
    b = make_brief(load_profile(), "2026-09-28", [])
    b["duration_s"] = seconds
    return b


def _mp3(tmp_path: Path, seconds=3) -> bytes:
    f = tmp_path / "tone.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f=110:d={seconds}", "-ac", "2", str(f)], check=True)
    return f.read_bytes()


def _refusal(code, body):
    return urllib.error.HTTPError("https://api.elevenlabs.io/v1/music", code, "err", {}, io.BytesIO(json.dumps(body).encode()))


def test_the_request_is_the_documented_one(monkeypatch, tmp_path):
    sent = []

    def post(self, body, fmt):
        sent.append((body, fmt))
        return _mp3(tmp_path), {"song-id": "s1"}

    monkeypatch.setattr(ElevenLabsEngine, "_post", post)
    wav, stats = ElevenLabsEngine(api_key="k").generate(_brief(150), tmp_path / "out")
    body, fmt = sent[0]
    assert fmt == "mp3_48000_192" and body["model_id"] == "music_v2_5" and body["force_instrumental"] is True
    assert body["music_length_ms"] == 150000 and 0 < len(body["prompt"]) <= 4100 and "BPM" in body["prompt"]
    assert wav.exists() and stats["engine"] == "elevenlabs" and stats["song_id"] == "s1"
    assert json.loads((tmp_path / "out" / "elevenlabs-request.json").read_text())["output_format"] == "mp3_48000_192"


def test_a_refused_prompt_is_retried_once_with_the_suggested_rewrite(monkeypatch, tmp_path):
    prompts = []

    def post(self, body, fmt):
        prompts.append(body["prompt"])
        if len(prompts) == 1:
            raise _refusal(422, {"detail": {"status": "bad_prompt", "data": {"prompt_suggestion": "hard techno, 154 BPM, instrumental"}}})
        return _mp3(tmp_path), {}

    monkeypatch.setattr(ElevenLabsEngine, "_post", post)
    ElevenLabsEngine(api_key="k").generate(_brief(), tmp_path / "out")
    assert prompts[1] == "hard techno, 154 BPM, instrumental"


def test_an_unoffered_format_falls_back_to_the_services_own(monkeypatch, tmp_path):
    fmts = []

    def post(self, body, fmt):
        fmts.append(fmt)
        if fmt == "mp3_48000_192":
            raise _refusal(422, {"detail": "output_format not available on this plan"})
        return _mp3(tmp_path), {}

    monkeypatch.setattr(ElevenLabsEngine, "_post", post)
    _, stats = ElevenLabsEngine(api_key="k").generate(_brief(), tmp_path / "out")
    assert fmts == ["mp3_48000_192", "auto"] and stats["output_format"] == "auto"


def test_other_refusals_stop_the_engine_so_the_next_one_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(ElevenLabsEngine, "_post", lambda self, b, f: (_ for _ in ()).throw(_refusal(401, {"detail": "invalid api key"})))
    with pytest.raises(ElevenLabsError, match="HTTP 401"):
        ElevenLabsEngine(api_key="k").generate(_brief(), tmp_path / "out")


def test_without_a_key_the_day_goes_to_the_next_engine(monkeypatch, tmp_path):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(elevenlabs, "env", lambda *a, **k: None)
    wav, stats = Fallback(ElevenLabsEngine(), FixtureEngine()).generate(_brief(12), tmp_path / "out")
    assert wav.exists() and stats["engine"] == "fixture" and stats["fallback_from"] == "elevenlabs"
    assert "ELEVENLABS_API_KEY" in stats["fallback_reason"]
