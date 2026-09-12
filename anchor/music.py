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


class AceStepCpp:
    name = "acestep_cpp"

    def __init__(self, bin_dir: str | Path, models_dir: str | Path, dit_model: str,
                 lm_model: str | None, steps: int = 8, shift: float = 3.0,
                 threads: int | None = None, vae_chunk: int = 512, timeout_s: int = 5400):
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
            "lyrics": "[Instrumental]",
            "bpm": int(brief["bpm"]),
            "duration": float(brief["duration_s"]),
            "keyscale": brief["key"],
            "timesignature": "4",
            "vocal_language": "unknown",
            "seed": int(brief["seed"]),
            "inference_steps": self.steps,
            "guidance_scale": 1.0,
            "shift": self.shift,
            "use_cot_caption": False,
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
        stats: dict = {"engine": self.name, "threads": self.threads}
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


def get_engine(profile_music: dict, name: str | None = None):
    name = name or env("ANCHOR_ENGINE") or profile_music.get("engine", "acestep_cpp")
    if name == "fixture":
        return FixtureEngine()
    if name == "acestep_cpp":
        return AceStepCpp(
            bin_dir=env("ACESTEP_BIN", "vendor/acestep.cpp/build"),
            models_dir=env("ACESTEP_MODELS", "vendor/models"),
            dit_model=profile_music["dit_model"],
            lm_model=profile_music.get("lm_model") if env("ANCHOR_USE_LM", "1") != "0" else None,
            steps=int(profile_music.get("steps", 8)),
            shift=float(profile_music.get("shift", 3.0)),
            threads=int(env("ACE_THREADS", "0") or 0) or None,
            vae_chunk=int(env("ANCHOR_VAE_CHUNK", "512")),
            timeout_s=int(env("ANCHOR_ENGINE_TIMEOUT", "5400")),
        )
    raise ValueError(f"unknown music engine {name!r}")
