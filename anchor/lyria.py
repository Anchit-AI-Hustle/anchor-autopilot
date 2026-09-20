"""Lyria 3.5 through the Gemini API: the paid, hosted engine.

One HTTPS call renders a full song (44.1 kHz stereo MP3, a couple of minutes, SynthID
watermarked) from a single text input. Lyria has no bpm / duration / key parameters: every
one of those is carried inside the prompt, which is exactly what the 9-layer style prompt
already does. Lyrics come back as text when the model sings; an instrumental returns none.

No SDK: the request is a plain JSON POST, the same way publish.py talks to Buffer.
The key is read from GEMINI_API_KEY and never logged.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import env
from .util import log, run

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
MODEL = "lyria-3.5"


class LyriaError(RuntimeError):
    pass


def compose_input(brief: dict) -> str:
    """One prompt for Lyria: the style sheet, then the arrangement sheet, then the hard facts.

    The duration is stated twice (in words and as a section timeline) because Lyria takes
    length from the prompt alone; the lyrics field's section tags become the timeline.
    """
    d = int(brief["duration_s"])
    mm, ss = divmod(d, 60)
    return "\n\n".join([
        brief["caption"],
        f"Length: exactly {mm}:{ss:02d} ({d} seconds). Tempo: {int(brief['bpm'])} BPM. "
        f"Key: {brief['key']}. Title: {brief['title']}.",
        "Arrangement, in order, as section tags:\n" + brief["lyrics"],
        "Avoid: " + brief.get("negative", ""),
    ])


def _blocks(obj, out: list) -> list:
    """Every dict with a 'type' key, anywhere in the response - the schema nests them under
    steps[].model_output[] today and may move them tomorrow."""
    if isinstance(obj, dict):
        if "type" in obj and ("data" in obj or "text" in obj):
            out.append(obj)
        for v in obj.values():
            _blocks(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _blocks(v, out)
    return out


def parse_response(payload: dict) -> tuple[bytes | None, str, str]:
    """(audio bytes, mime type, lyrics text) out of an interactions response."""
    audio, mime, text = None, "", []
    for b in _blocks(payload, []):
        t = str(b.get("type", "")).lower()
        if t == "audio" and b.get("data") and audio is None:
            audio = base64.b64decode(b["data"])
            mime = b.get("mime_type") or b.get("mimeType") or "audio/mpeg"
        elif t == "text" and b.get("text"):
            text.append(str(b["text"]))
    return audio, mime, "\n".join(text).strip()


class LyriaEngine:
    name = "lyria"

    def __init__(self, api_key: str | None = None, timeout_s: int = 600, attempts: int = 2,
                 wav: bool = False):
        self.api_key = api_key or env("GEMINI_API_KEY") or ""
        self.timeout_s = timeout_s
        self.attempts = attempts
        self.wav = wav

    def check(self) -> None:
        if not self.api_key:
            raise LyriaError("GEMINI_API_KEY is not set")

    def request(self, brief: dict) -> dict:
        req = {"model": MODEL, "input": compose_input(brief)}
        if self.wav:
            req["response_format"] = {"type": "audio"}
        return req

    def _call(self, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(ENDPOINT, data=data, method="POST", headers={
            "Content-Type": "application/json", "x-goog-api-key": self.api_key})
        last = None
        for attempt in range(self.attempts):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as exc:
                text = exc.read().decode(errors="replace")[:400]
                last = f"HTTP {exc.code}: {text}"
                if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < self.attempts:
                    time.sleep(20 * (attempt + 1))
                    continue
                raise LyriaError(last) from exc
            except urllib.error.URLError as exc:
                last = f"network error: {exc}"
                if attempt + 1 < self.attempts:
                    time.sleep(20)
                    continue
                raise LyriaError(last) from exc
        raise LyriaError(last or "unreachable")

    def generate(self, brief: dict, out_dir: Path) -> tuple[Path, dict]:
        self.check()
        out_dir.mkdir(parents=True, exist_ok=True)
        body = self.request(brief)
        (out_dir / "lyria-request.json").write_text(json.dumps(body, indent=2))
        started = time.monotonic()
        payload = self._call(body)
        (out_dir / "lyria-response.json").write_text(json.dumps(
            {k: v for k, v in payload.items() if k != "steps"} | {"steps": "<omitted: audio>"}, indent=2))
        audio, mime, lyrics = parse_response(payload)
        if not audio:
            raise LyriaError("Lyria returned no audio block")
        ext = ".wav" if "wav" in mime or self.wav else ".mp3"
        raw = out_dir / f"lyria{ext}"
        raw.write_bytes(audio)
        if lyrics:
            (out_dir / "lyrics.txt").write_text(lyrics, encoding="utf-8")
        # the mastering chain reads WAV; keep the original next to it untouched
        wav = out_dir / "gen0.wav"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-ar", "48000", "-ac", "2", str(wav)])
        stats = {"engine": self.name, "model": MODEL, "total_s": round(time.monotonic() - started, 1),
                 "mime": mime, "bytes": len(audio), "lyrics": lyrics or None,
                 "watermark": "SynthID"}
        log(f"lyria done in {stats['total_s']}s -> {wav.name} ({len(audio) / 1e6:.1f} MB, "
            f"{'lyrics' if lyrics else 'instrumental'})")
        return wav, stats
