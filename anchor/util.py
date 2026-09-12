"""Small shared helpers: logging, subprocess, seeded RNG, ffprobe."""
from __future__ import annotations

import hashlib
import json
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}", file=sys.stderr, flush=True)


def seed_from(*parts: object) -> int:
    """Stable 32-bit seed from any values (same inputs -> same seed on every machine)."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:8], 16)


def rng(*parts: object) -> random.Random:
    return random.Random(seed_from(*parts))


def run(cmd: list[str], *, timeout: int | None = None, cwd: Path | None = None,
        env: dict | None = None, quiet: bool = False) -> subprocess.CompletedProcess:
    """Run a command; raise with the tail of its output if it fails."""
    started = time.monotonic()
    if not quiet:
        log("$ " + " ".join(str(c) for c in cmd[:6]) + (" ..." if len(cmd) > 6 else ""))
    proc = subprocess.run(
        [str(c) for c in cmd], cwd=cwd, env=env, timeout=timeout,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stdout.splitlines()[-25:])
        raise RuntimeError(f"command failed ({proc.returncode}) after "
                           f"{time.monotonic() - started:.0f}s: {cmd[0]}\n{tail}")
    return proc


def ffprobe(path: Path) -> dict:
    proc = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                "-show_streams", str(path)], quiet=True)
    return json.loads(proc.stdout)


def media_summary(path: Path) -> dict:
    info = ffprobe(path)
    out = {"duration": float(info["format"].get("duration", 0.0)),
           "size_bytes": int(info["format"].get("size", 0))}
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":
            rate = stream.get("r_frame_rate", "0/1").split("/")
            out.update(width=int(stream["width"]), height=int(stream["height"]),
                       vcodec=stream.get("codec_name"), pix_fmt=stream.get("pix_fmt"),
                       fps=round(float(rate[0]) / max(float(rate[1]), 1.0), 3))
        elif stream.get("codec_type") == "audio":
            out.update(acodec=stream.get("codec_name"),
                       sample_rate=int(stream.get("sample_rate", 0)),
                       channels=int(stream.get("channels", 0)))
    return out


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default: object = None) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
