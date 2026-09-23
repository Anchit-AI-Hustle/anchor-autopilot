"""Music engines.

``acestep_cpp`` runs ACE-Step 1.5 (MIT licence, commercial use allowed) through the
acestep.cpp GGML port on plain CPU - no GPU, no API key, no cost.
``fixture`` synthesises a simple techno loop; it exists for tests and dry runs only.
"""
from __future__ import annotations

import json
import os
import re
import time
import wave
from pathlib import Path

import numpy as np

from .config import env
from .util import log, run

SR = 48_000


# A track that "just stops" was never composed: asked for N seconds with no arrangement,
# the model renders N seconds of loop and runs out mid-bar. ACE-Step reads the lyrics field
# as the arrangement, so the sections are named there - and the last one is always an outro,
# which is what gives the track somewhere to land instead of a cliff.
#
# Each section also carries a performance direction, the way a Suno/ACE lyrics sheet does
# ("[Bridge - instruments drop out]"): the arranger is told what happens over time, not just
# handed a list of ingredients, which is what stops every bar sounding equally loud.
SECTION_DIRECTIONS = {
    "intro": "filtered kick alone, no sub bass yet, {t0} far back, tension only",
    "build": "hi-hats and {t1} enter, filter opening, pressure rising bar by bar",
    "drop": "full distorted kick, sub bass in, {t1} on top, main hook at peak energy",
    "breakdown": "kick and sub fully out for eight to sixteen bars, {t2} alone over a held drone, the room drops away, tension kept",
    "build2": "snare roll and riser, every element pulled back in",
    "drop2": "harder than the first drop, everything at once",
    "outro": "kick and bass strip back, filter closing, {t0} last, resolve to silence",
}


# The shapes a full-length record can take. One is drawn per day (brief.make_brief), so
# consecutive records do not share a timeline even when the sound is close: the spectral
# sequence gate in unique.py measured 0.65 between two acid tracks cut to the same shape.
SHAPES = {
    "classic": ["intro", "build", "drop", "breakdown", "build2", "drop2", "outro"],
    "early": ["intro", "drop", "breakdown", "build2", "drop2", "outro"],            # the drop comes first
    "peak": ["intro", "build", "drop", "drop2", "breakdown", "drop2", "outro"],     # a long peak, a late breakdown
    "twice": ["intro", "build", "drop", "breakdown", "drop2", "build2", "drop2", "outro"],  # two returns
}


def arrangement(duration_s: float, textures: tuple[str, ...] = (), shape: str = "classic") -> list[tuple[str, str]]:
    """The ordered sections for a track of this length, each with its direction.

    Sizes are chosen so each section gets roughly 8-16 bars at this channel's tempo, which
    is how the genre is actually built: filtered intro, build, drop, breakdown, drop, outro.
    ``shape`` picks one of ``SHAPES`` for a full-length record (130-210 s).
    """
    if duration_s < 75:
        parts = ["intro", "drop", "outro"]
    elif duration_s < 130:
        parts = ["intro", "build", "drop", "breakdown", "outro"]
    elif duration_s < 210:
        parts = SHAPES.get(shape, SHAPES["classic"])
    else:
        parts = ["intro", "build", "drop", "breakdown", "build2", "drop2", "breakdown",
                 "drop2", "outro"]
    tex = list(textures) or ["noise", "percussion", "drone"]
    while len(tex) < 3:
        tex.append(tex[-1])
    fill = {"t0": tex[0], "t1": tex[1], "t2": tex[2]}
    return [(name.rstrip("2"), SECTION_DIRECTIONS[name].format(**fill)) for name in parts]


def structure(duration_s: float, textures: tuple[str, ...] = (), shape: str = "classic") -> str:
    """The lyrics-field arrangement: one bracketed section per line, direction attached."""
    return "\n".join(f"[{tag} - {direction}]" for tag, direction in arrangement(duration_s, textures, shape))


def arc(duration_s: float, textures: tuple[str, ...] = (), shape: str = "classic") -> str:
    """The arrangement as one line of prose for the style prompt.

    The lyrics field carries the full per-section directions; the caption only needs the
    shape, so the encoder's budget goes on sound rather than on repeating the sheet.
    """
    steps = arrangement(duration_s, textures, shape)
    tags = " -> ".join(tag for tag, _ in steps)
    last = steps[-1][1]
    return f"Arrangement: {tags}; {steps[0][1]} at the start, and the outro {last}"


class AceStepCpp:
    name = "acestep_cpp"

    def __init__(self, bin_dir: str | Path, models_dir: str | Path, dit_model: str,
                 lm_model: str | None, steps: int = 8, shift: float = 3.0,
                 guidance: float = 1.0, threads: int | None = None,
                 vae_chunk: int = 512, timeout_s: int = 5400):
        # absolute: the binaries run with cwd set to the drop folder, so a relative
        # path here would resolve against that folder instead of the repo
        self.bin_dir = Path(bin_dir).expanduser().resolve()
        self.models_dir = Path(models_dir).expanduser().resolve()
        self.dit_model = dit_model if dit_model.endswith(".gguf") else dit_model + ".gguf"
        self.lm_model = None
        if lm_model:
            self.lm_model = lm_model if lm_model.endswith(".gguf") else lm_model + ".gguf"
        self.steps = steps
        self.shift = shift
        self.guidance = float(guidance)
        self.threads = threads or os.cpu_count() or 2
        self.vae_chunk = vae_chunk
        self.timeout_s = timeout_s

    def check(self) -> None:
        missing = [str(p) for p in (self.bin_dir / "ace-synth", self.models_dir / self.dit_model)
                   if not p.exists()]
        if self.lm_model:
            for p in (self.bin_dir / "ace-lm", self.models_dir / self.lm_model):
                if not p.exists():
                    missing.append(str(p))
        if missing:
            raise FileNotFoundError("acestep.cpp not ready, missing: " + ", ".join(missing))

    def request(self, brief: dict) -> dict:
        req = {
            "caption": brief["caption"],
            "lyrics": brief.get("lyrics") or structure(float(brief["duration_s"])),
            "bpm": int(brief["bpm"]),
            "duration": float(brief["duration_s"]),
            "keyscale": brief["key"],
            "timesignature": "4",
            "vocal_language": "unknown",
            "seed": int(brief["seed"]),
            "inference_steps": self.steps,
            # CFG is what makes the model actually follow the caption. The turbo DiT is
            # distilled and silently clamps this to 1.0, which is why "acid" came out as
            # generic techno no matter how the prompt was written; the sft DiT honours it.
            "guidance_scale": float(self.guidance),
            "shift": self.shift,
            "use_cot_caption": True,   # let the LM enrich the caption: it follows the genre better
            "output_format": "wav16",
            "synth_model": self.dit_model,
        }
        if self.lm_model:
            req["lm_model"] = self.lm_model
            req["lm_negative_prompt"] = brief.get("negative", "")
        return req

    def generate(self, brief: dict, out_dir: Path) -> tuple[Path, dict]:
        self.check()
        out_dir.mkdir(parents=True, exist_ok=True)
        stats: dict = {"engine": self.name, "threads": self.threads, "steps": self.steps,
                       "model": self.dit_model, "guidance": self.guidance}
        proc_env = {**os.environ, "ACE_THREADS": str(self.threads)}
        req_path = out_dir / "gen.json"
        req_path.write_text(json.dumps(self.request(brief), indent=2))
        synth_input = req_path.name
        started = time.monotonic()
        if self.lm_model:
            proc = run([self.bin_dir / "ace-lm", "--models", self.models_dir, "--request", req_path.name],
                       cwd=out_dir, env=proc_env, timeout=self.timeout_s)
            (out_dir / "ace-lm.log").write_text(proc.stdout)
            stats["lm_ms"] = _ms(proc.stdout, r"\[Ace-LM\] Total (\d+)ms")
            synth_input = "gen0.json"
            if not (out_dir / synth_input).exists():
                raise RuntimeError("ace-lm finished but gen0.json was not written")
        proc = run([self.bin_dir / "ace-synth", "--models", self.models_dir, "--request", synth_input,
                    "--vae-chunk", str(self.vae_chunk), "--vae-overlap", "64"],
                   cwd=out_dir, env=proc_env, timeout=self.timeout_s)
        (out_dir / "ace-synth.log").write_text(proc.stdout)
        stats["dit_ms"] = _ms(proc.stdout, r"\[DiT-Generate\] Total: ([\d.]+) ms")
        stats["vae_ms"] = _ms(proc.stdout, r"Decode: ([\d.]+) ms")
        stats["total_s"] = round(time.monotonic() - started, 1)
        wav = out_dir / (Path(synth_input).stem + "0.wav")
        if not wav.exists():
            candidates = sorted(out_dir.glob("*.wav"))
            if not candidates:
                raise RuntimeError("ace-synth finished but no WAV was written")
            wav = candidates[-1]
        log(f"acestep.cpp done in {stats['total_s']}s -> {wav.name}")
        return wav, stats


def _ms(text: str, pattern: str) -> float | None:
    m = re.findall(pattern, text)
    return round(float(m[-1])) if m else None


class FixtureEngine:
    """Deterministic synthetic techno for tests (kick, rumble, hats, clap, acid line)."""
    name = "fixture"

    def generate(self, brief: dict, out_dir: Path) -> tuple[Path, dict]:
        out_dir.mkdir(parents=True, exist_ok=True)
        wav = out_dir / "fixture.wav"
        audio = synth_techno(float(brief["duration_s"]), int(brief["bpm"]), int(brief["seed"]))
        write_wav(wav, audio)
        return wav, {"engine": self.name, "total_s": 0.0}


def synth_techno(duration: float, bpm: int, seed: int) -> np.ndarray:
    rs = np.random.default_rng(seed)
    n = int(duration * SR)
    t_beat = 60.0 / bpm
    out = np.zeros(n, dtype=np.float64)

    def place(sample: np.ndarray, at: float, gain: float = 1.0) -> None:
        i = int(at * SR)
        if i >= n:
            return
        j = min(n, i + len(sample))
        out[i:j] += gain * sample[: j - i]

    tk = np.arange(int(0.35 * SR)) / SR
    kick = np.sin(2 * np.pi * (45 * tk + 180 * (1 - np.exp(-tk * 30)) / 30)) * np.exp(-tk * 9)
    kick = np.tanh(kick * 4.0)
    th = np.arange(int(0.05 * SR)) / SR
    hat = rs.standard_normal(len(th)) * np.exp(-th * 90)
    hat = np.diff(hat, prepend=0.0)
    tc = np.arange(int(0.18 * SR)) / SR
    clap = rs.standard_normal(len(tc)) * np.exp(-tc * 25)
    beats = int(duration / t_beat)
    for b in range(beats):
        at = b * t_beat
        bar = b // 4
        intro = bar < 8
        outro = at > duration - 8 * 4 * t_beat
        if not intro or bar % 2 == 0:
            place(kick, at, 0.9 if not (intro or outro) else 0.55)
        place(hat, at + t_beat / 2, 0.25)
        if b % 2 == 1 and not intro:
            place(clap, at, 0.35)
        if not intro and not outro:
            tb = np.arange(int(t_beat / 2 * SR)) / SR
            freq = 55 * (2 ** (rs.integers(0, 4) * 3 / 12))
            place(np.tanh(3 * np.sin(2 * np.pi * freq * tb)) * np.exp(-tb * 6), at + t_beat / 2, 0.35)
    peak = np.max(np.abs(out)) or 1.0
    mono = 0.8 * out / peak
    stereo = np.stack([mono, np.roll(mono, 24)], axis=1)
    return stereo.astype(np.float32)


def write_wav(path: Path, audio: np.ndarray, sr: int = SR) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(audio.shape[1] if audio.ndim == 2 else 1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


class Fallback:
    """Try the first engine; on its own error (missing key, API failure), use the second.

    A QC failure is not an engine error: that comes back as a normal result and the
    pipeline retries with a new seed as before.
    """
    def __init__(self, primary, secondary):
        self.primary, self.secondary = primary, secondary
        self.name = f"{primary.name}->{secondary.name}"

    def generate(self, brief: dict, out_dir):
        try:
            self.primary.check()
            return self.primary.generate(brief, out_dir)
        except Exception as exc:                          # noqa: BLE001 - any engine failure
            log(f"{self.primary.name} unavailable ({str(exc)[:160]}); falling back to {self.secondary.name}")
            wav, stats = self.secondary.generate(brief, out_dir)
            stats["fallback_from"] = self.primary.name
            stats["fallback_reason"] = str(exc)[:200]
            return wav, stats


def get_engine(profile_music: dict, name: str | None = None):
    name = name or env("ANCHOR_ENGINE") or profile_music.get("engine", "acestep_cpp")
    if name == "fixture":
        return FixtureEngine()
    if name == "lyria":
        from .lyria import LyriaEngine
        engine = LyriaEngine(wav=bool(profile_music.get("lyria_wav", False)))
        fb = profile_music.get("fallback_engine")
        return Fallback(engine, get_engine(profile_music, fb)) if fb and fb != "lyria" else engine
    if name == "acestep_cpp":
        return AceStepCpp(
            bin_dir=env("ACESTEP_BIN", "vendor/acestep.cpp/build"),
            models_dir=env("ACESTEP_MODELS", "vendor/models"),
            dit_model=profile_music["dit_model"],
            lm_model=profile_music.get("lm_model") if env("ANCHOR_USE_LM", "1") != "0" else None,
            steps=int(profile_music.get("steps", 8)),
            shift=float(profile_music.get("shift", 3.0)),
            guidance=float(profile_music.get("guidance", 1.0)),
            threads=int(env("ACE_THREADS", "0") or 0) or None,
            vae_chunk=int(env("ANCHOR_VAE_CHUNK", "512")),
            timeout_s=int(env("ANCHOR_ENGINE_TIMEOUT", "5400")),
        )
    raise ValueError(f"unknown music engine {name!r}")
