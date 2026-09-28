"""Eleven Music through the ElevenLabs API: an official, documented music API.

POST https://api.elevenlabs.io/v1/music with the prompt, the length in milliseconds and
force_instrumental; the answer is the audio file itself (docs checked 2026-09-28:
elevenlabs.io/docs/api-reference/music/compose). A prompt the service refuses as naming
protected material comes back as a 4xx "bad_prompt" with a suggested rewrite, which is
tried once. The key is read from ELEVENLABS_API_KEY and never logged. Needs a paid plan.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import env
from .lyria import compose_input
from .util import log, run

ENDPOINT = "https://api.elevenlabs.io/v1/music"
MODEL = "music_v2_5"
FORMATS = ("mp3_48000_192", "auto")      # the documented v2 format first, the service's own choice second
MAX_PROMPT = 4100


class ElevenLabsError(RuntimeError):
    pass


def prompt_for(brief: dict) -> str:
    """The same style, arrangement and length sheet Lyria gets, cut to the API's limit."""
    return compose_input(brief)[:MAX_PROMPT]


def suggestion(body: str) -> str | None:
    """The rewrite the service offers with a bad_prompt refusal, if there is one."""
    try:
        detail = json.loads(body).get("detail") or {}
    except ValueError:
        return None
    if isinstance(detail, dict) and detail.get("status") == "bad_prompt":
        return (detail.get("data") or {}).get("prompt_suggestion")
    return None


class ElevenLabsEngine:
    name = "elevenlabs"

    def __init__(self, api_key: str | None = None, model: str = MODEL, timeout_s: int = 600):
        self.api_key = api_key or env("ELEVENLABS_API_KEY") or ""
        self.model = model
        self.timeout_s = timeout_s

    def check(self) -> None:
        if not self.api_key:
            raise ElevenLabsError("ELEVENLABS_API_KEY is not set")

    def request(self, brief: dict, prompt: str | None = None) -> dict:
        ms = int(round(float(brief["duration_s"]) * 1000))
        return {"prompt": prompt or prompt_for(brief), "music_length_ms": max(3000, min(600000, ms)),
                "model_id": self.model, "force_instrumental": True}

    def _post(self, body: dict, fmt: str) -> tuple[bytes, dict]:
        url = ENDPOINT + "?" + urllib.parse.urlencode({"output_format": fmt})
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "xi-api-key": self.api_key})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return resp.read(), dict(resp.headers)

    def _call(self, body: dict) -> tuple[bytes, dict, dict]:
        """(audio, headers, the body that worked). Tries the documented format, then the
        service's own; a bad_prompt refusal is retried once with the suggested rewrite;
        a busy or failing service is retried once after a pause."""
        last = None
        for fmt in FORMATS:
            for attempt in range(2):
                try:
                    audio, headers = self._post(body, fmt)
                    return audio, headers, {**body, "output_format": fmt}
                except urllib.error.HTTPError as exc:
                    text = exc.read().decode(errors="replace")[:800]
                    last = f"HTTP {exc.code}: {text[:300]}"
                    better = suggestion(text)
                    if better and attempt == 0:
                        log("elevenlabs: prompt refused as bad_prompt; retrying with the suggested rewrite")
                        body = {**body, "prompt": better[:MAX_PROMPT]}
                        continue
                    if exc.code in (429, 500, 502, 503, 504) and attempt == 0:
                        time.sleep(20)
                        continue
                    if exc.code in (400, 422) and "output_format" in text:
                        break                      # this format is not offered: try the next one
                    raise ElevenLabsError(last) from exc
                except urllib.error.URLError as exc:
                    last = f"network error: {exc}"
                    if attempt == 0:
                        time.sleep(20)
                        continue
                    raise ElevenLabsError(last) from exc
        raise ElevenLabsError(last or "no output format accepted")

    def generate(self, brief: dict, out_dir: Path) -> tuple[Path, dict]:
        self.check()
        out_dir.mkdir(parents=True, exist_ok=True)
        body = self.request(brief)
        started = time.monotonic()
        audio, headers, sent = self._call(body)
        (out_dir / "elevenlabs-request.json").write_text(json.dumps(sent, indent=2))
        if len(audio) < 10_000:
            raise ElevenLabsError(f"ElevenLabs returned {len(audio)} bytes, not a song")
        raw = out_dir / "elevenlabs.audio"
        raw.write_bytes(audio)
        # the mastering chain reads WAV; the original stays next to it untouched
        wav = out_dir / "gen0.wav"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-ar", "48000", "-ac", "2", str(wav)])
        song_id = next((v for k, v in headers.items() if k.lower() == "song-id"), None)
        stats = {"engine": self.name, "model": self.model, "total_s": round(time.monotonic() - started, 1),
                 "bytes": len(audio), "output_format": sent["output_format"], "song_id": song_id, "lyrics": None}
        log(f"elevenlabs done in {stats['total_s']}s -> {wav.name} ({len(audio) / 1e6:.1f} MB)")
        return wav, stats
