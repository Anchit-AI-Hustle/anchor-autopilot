"""One version of every record, everywhere: the site, the release, the Short and the video.

``site/data/versions.json`` names, for each record that needs it, the source to build from
(a release master or the original Suno render), what to do to it (weld two takes, extend the
arrangement, tame the fizz, the finishing pass) and the YouTube videos it replaces. ``build``
makes the new master, MP3, FLAC and Short from public sources, so the same entry gives the
same record on any machine; the release assets are replaced under their old names, so every
link the site already has keeps working; ``publish`` uploads the new video and Short with the
old ones' words and sets the old ones to private (never deleted); ``record`` writes the new
length, loudness and links into the catalog. Every step is idempotent per entry.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import numpy as np

from . import craft
from .audio import SR, beat_phase, decode, encode_flac, encode_mp3, master
from .config import CATALOG_PATH, Profile
from .ledger import clean_title
from .music import write_wav
from .unique import envelope
from .util import iso, log, read_json, run, utcnow, write_json
from .video import AAC_CLEAN

VERSIONS_PATH = CATALOG_PATH.parent / "versions.json"
RELEASES = "https://github.com/{repo}/releases/download/{tag}/{file}"
SUNO = "https://cdn1.suno.ai/{id}.mp4"


# ---------------------------------------------------------------------- sources
def source_url(src: dict, repo: str) -> str:
    if "suno" in src:
        return SUNO.format(id=src["suno"])
    return RELEASES.format(repo=repo, tag=src["release"], file=src["file"])


def fetch(url: str, dst: Path, min_bytes: int = 50_000) -> Path:
    """Download once; a file under ``min_bytes`` is a stub or an error page, never a source."""
    if not dst.exists() or dst.stat().st_size < min_bytes:
        dst.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, dst)
    if dst.stat().st_size < min_bytes:
        raise RuntimeError(f"{url} gave only {dst.stat().st_size} bytes")
    return dst


def original(name: str) -> str:
    """The name the release keeps the first master under once a new version replaces it:
    ``x.flac`` -> ``x-original.flac``, ``x-short.mp4`` -> ``x-short-original.mp4``."""
    stem, ext = name.rsplit(".", 1)
    return f"{stem}-original.{ext}"


def release_fetch(repo: str, tag: str, name: str, dst: Path, min_bytes: int = 50_000) -> Path:
    """A release asset as it was before any new version: the kept original when there is one,
    so building an entry twice never processes its own output."""
    try:
        return fetch(RELEASES.format(repo=repo, tag=tag, file=original(name)), dst, min_bytes)
    except (OSError, RuntimeError):          # urllib's HTTPError is an OSError; no original yet
        return fetch(RELEASES.format(repo=repo, tag=tag, file=name), dst, min_bytes)


def load_source(src: dict, repo: str, work: Path) -> np.ndarray:
    name = src.get("suno") or src["file"]
    dst = work / "src" / (name if "." in name else f"{name}.mp4")
    path = fetch(source_url(src, repo), dst) if "suno" in src else release_fetch(repo, src["release"], src["file"], dst)
    audio = decode(path).astype(np.float32)
    start = float(src.get("from", 0.0))
    return audio[int(start * SR):]


# ------------------------------------------------------------------------- edits
def weld(parts: list[np.ndarray], at: list[float]) -> np.ndarray:
    """Part k enters at ``at[k]`` seconds and the one before it fades out under it
    (equal power) until it ends."""
    out = parts[0]
    for p, t in zip(parts[1:], at[1:]):
        i = int(t * SR)
        over = max(0, min(len(out) - i, len(p)))
        r = np.linspace(0, 1, over, dtype=np.float32)[:, None]
        mixed = out[i:i + over] * np.sqrt(1 - r) + p[:over] * np.sqrt(r)
        out = np.concatenate([out[:i], mixed, p[over:]])
    return out


def _join(first: np.ndarray, rest: list[np.ndarray], x: int) -> np.ndarray:
    """Butt parts together. Each later part carries ``x`` samples of what came before it in
    the source (its pre-roll), which fade in under the last ``x`` samples of the part before, so
    every part starts exactly on its mark and the record's length and grid never move."""
    r = np.linspace(0, 1, x, dtype=np.float32)[:, None]
    out = [first[:-x]]
    tail = first[-x:]
    for p in rest:
        out.append(tail * (1 - r) + p[:x] * r)
        out.append(p[x:-x])
        tail = p[-x:]
    out.append(tail)
    return np.concatenate(out)


def extend(audio: np.ndarray, bpm: float, *, breakdown_from: tuple[int, int], before_bar: int,
           repeat: tuple[int, int], outro_bar: int, bars: int = 16) -> np.ndarray:
    """Insert a breakdown built from the record itself and play a phrase twice.

    Bars ``before_bar`` onward are pushed back by a ``bars``-bar breakdown made from bars
    ``breakdown_from`` (kick and sub filtered out for the first half, the filter closing back
    down over the second so the kick returns bar by bar), then the phrase ``repeat`` plays
    again before the outro at ``outro_bar``. Every cut lands on a bar of the record's own grid
    and every added section is whole bars, so the kick never shifts."""
    phase, bar = beat_phase(audio.mean(axis=1), bpm), 4 * 60.0 / bpm
    x = int(0.004 * SR)
    at = lambda b: int(round((phase + b * bar) * SR))           # noqa: E731
    seg = lambda a, b: audio[at(a) - x:at(b)]                   # noqa: E731, with its pre-roll
    n_bar = int(round(bar * SR))
    src = seg(*breakdown_from)
    reps = int(np.ceil(bars * n_bar / (len(src) - x)))
    loop = np.concatenate([src[:x], _join(src[x:], [src] * (reps - 1), x)])[: x + bars * n_bar]
    # one continuous filter per cutoff over the whole loop, then bar by bar from the right one
    cuts = [150.0 if i < bars // 2 else 150.0 * (35 / 150) ** ((i - bars // 2 + 1) / (bars // 2)) for i in range(bars)]
    spec = np.fft.rfft(loop, axis=0)
    filtered = {fc: np.fft.irfft(spec * craft._band(len(loop), SR, fc, SR / 2, edge=0.35)[:, None], len(loop), axis=0)
                for fc in sorted(set(cuts))}
    bar_parts = [filtered[fc][i * n_bar:x + (i + 1) * n_bar] for i, fc in enumerate(cuts)]
    brk = np.concatenate([bar_parts[0][:x], _join(bar_parts[0][x:], bar_parts[1:], x)])
    out = _join(audio[:at(before_bar)], [brk, seg(before_bar, outro_bar), seg(*repeat), audio[at(outro_bar) - x:]], x)
    return out.astype(np.float32)


# ------------------------------------------------------------------------- build
def find_window(short_audio: np.ndarray, full: np.ndarray) -> tuple[float, float]:
    """(start seconds, match) of the Short's cut inside a full master, by loudness envelope."""
    a = envelope(short_audio.mean(axis=1), SR)
    b = envelope(full.mean(axis=1), SR)
    a = a - a.mean()
    best = (0.0, 0.0)
    for k in range(0, max(1, len(b) - len(a))):
        seg = b[k:k + len(a)]
        seg = seg - seg.mean()
        c = float(a @ seg / ((np.linalg.norm(a) * np.linalg.norm(seg)) or 1.0))
        if c > best[1]:
            best = (k * 0.1, c)
    return best


def build(profile: Profile, entry: dict, drop: dict, repo: str, work: Path) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    base = drop["audio_url"].split("?")[0].rsplit("/", 1)[-1].rsplit(".", 1)[0]
    tag = f"drop-{drop['id']}"
    srcs = entry["source"] if isinstance(entry["source"], list) else [entry["source"]]
    parts = [load_source(s, repo, work) for s in srcs]
    audio = weld(parts, [float(s.get("at", 0.0)) for s in srcs]) if len(parts) > 1 else parts[0]
    notes = []
    if entry.get("extend"):
        audio = extend(audio, float(drop["bpm"]), **{k: tuple(v) if isinstance(v, list) else v for k, v in entry["extend"].items()})
        notes.append("arrangement extended with a breakdown")
    arranged = audio                     # the timeline the Short is found on; tame and finish do not move it
    if entry.get("tame"):
        audio, info = craft.tame_fizz(audio)
        notes.append(f"fizz tamed on {info['frames_cut']:.0%} of frames, at most {info['max_cut_db']} dB")
    if entry.get("finish", True):
        audio, info = craft.enhance(audio)
        notes.append(f"finishing pass tone {info.get('tone', 0)}, width {info.get('spread', 0)}")
    raw = work / "premaster.wav"
    write_wav(raw, audio / (np.abs(audio).max() + 1e-9) * 0.9)
    mwav = work / "master.wav"
    loud = master(raw, mwav, float(profile.music["loudness_lufs"]), float(profile.music["true_peak_db"]))
    new = decode(mwav)
    files = {"mp3": work / f"{base}.mp3", "flac": work / f"{base}.flac", "short": work / f"{base}-short.mp4"}
    cover = fetch(RELEASES.format(repo=repo, tag=tag, file=f"{base}-cover.jpg"), work / "src" / f"{base}-cover.jpg", 20_000)
    encode_flac(mwav, files["flac"])
    encode_mp3(mwav, files["mp3"], tags={"title": clean_title(drop["title"]), "artist": profile.artist["name"],
                                         "album_artist": profile.artist["name"], "album": profile.artist["name"],
                                         "date": drop["date"], "genre": drop.get("lane_name", "Techno"),
                                         "TBPM": str(int(drop["bpm"])), "WOAR": profile.artist["site_url"]}, cover=cover)
    # the Short keeps its picture and its place in the record; only the sound is the new master's
    old_short = release_fetch(repo, tag, f"{base}-short.mp4", work / "src" / f"{base}-short-old.mp4")
    old_audio = decode(old_short)
    start, match = find_window(old_audio, arranged)
    if match < 0.75:
        raise RuntimeError(f"{drop['title']}: the Short's cut was not found in the new master (match {match:.2f})")
    length = len(old_audio) / SR
    cutwav = work / "short.wav"
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", mwav,
         "-af", f"afade=t=in:st=0:d=0.35,afade=t=out:st={max(0.0, length - 1.6):.3f}:d=1.6", "-ar", str(SR), cutwav], quiet=True)
    run(["ffmpeg", "-y", "-v", "error", "-i", old_short, "-i", cutwav, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", *AAC_CLEAN, "-shortest", "-movflags", "+faststart", files["short"]], quiet=True)
    meta = {"id": drop["id"], "title": clean_title(drop["title"]), "base": base, "tag": tag,
            "duration_s": round(len(new) / SR, 2), "loudness": loud["after"], "notes": notes,
            "short": {"start_s": round(start, 1), "match": round(match, 3), "length_s": round(length, 1)},
            "craft_after": {k: v for k, v in craft.measure(new).items() if k != "breakdowns"},
            "files": {k: v.name for k, v in files.items()}, "built_at": iso(utcnow())}
    write_json(work / "meta.json", meta)
    log(f"versions: {drop['title']}: {meta['duration_s']} s, {loud['after']['input_i']} LUFS / {loud['after']['input_tp']} dBTP; "
        f"Short found at {start:.1f} s ({match:.2f}); {'; '.join(notes)}")
    return meta


# ----------------------------------------------------------------------- publish
def publish(profile: Profile, entry: dict, meta: dict, work: Path, api=None) -> dict:
    """New full video (the old one's thumbnail as its frame, a moving waveform) and new Short
    on YouTube with the old ones' words; the old ones set to private, never deleted.

    Each step is written to ``entry["publishing"]`` as it lands, so a run that stops halfway
    picks up where it stopped and never uploads the same video twice."""
    from .video import render_motion
    from .youtube import YouTube, playlist_id
    api = api or YouTube()
    yt = entry["youtube"]
    state = entry.setdefault("publishing", {})
    old = {v["id"]: v for v in api.videos([yt["full"], yt["short"]])}
    missing = [v for v in (yt["full"], yt["short"]) if v not in old]
    if missing:
        raise RuntimeError(f"{meta['title']}: {', '.join(missing)} not on the channel; check site/data/versions.json")
    f, s = old[yt["full"]], old[yt["short"]]
    if "full" not in state:
        frame = fetch(f"https://i.ytimg.com/vi/{yt['full']}/maxresdefault.jpg", work / "frame.jpg", 20_000)
        video = work / f"{meta['base']}-full-169.mp4"
        render_motion(frame, work / meta["files"]["mp3"], video, entry.get("accent", "#d8742f"), crf=23, timeout=3600)
        full = api.upload(video, title=f["title"], description=f["description"], tags=f["tags"], category_id=f["categoryId"],
                          ai_generated=True, notify=False)
        state["full"] = {"id": full["id"], "url": full["url"]}
        try:
            api.set_thumbnail(full["id"], frame)
        except Exception as exc:          # noqa: BLE001 - cosmetic
            log(f"versions: thumbnail failed: {exc}")
        pl = playlist_id(profile.youtube.get("playlist_url"))
        if pl:
            api.add_to_playlist(full["id"], pl)
    full = state["full"]
    if "short" not in state:
        sdesc = "\n".join(f"Full track: {full['url']}" if line.startswith("Full track:") else line for line in s["description"].split("\n"))
        if "Full track:" not in sdesc:
            sdesc = sdesc.replace("\n\n", f"\n\nFull track: {full['url']}\n", 1)
        short = api.upload(work / meta["files"]["short"], title=s["title"], description=sdesc, tags=s["tags"],
                           category_id=s["categoryId"], ai_generated=True, notify=False)
        state["short"] = {"id": short["id"], "url": short["url"]}
    for vid in (yt["full"], yt["short"]):
        if vid not in state.setdefault("private", []):
            api.set_privacy(vid, "private")
            state["private"].append(vid)
    entry.pop("publishing")
    log(f"versions: {meta['title']}: new video {full['id']}, new Short {state['short']['id']}; "
        f"{yt['full']} and {yt['short']} set to private")
    return {"full": full["id"], "short": state["short"]["id"], "replaced": [yt["full"], yt["short"]], "published_at": iso(utcnow())}


# ------------------------------------------------------------------------ record
def record(catalog: dict, entry: dict, meta: dict, pub: dict | None) -> None:
    for d in catalog.get("drops", []):
        if d["id"] != meta["id"]:
            continue
        d["duration_s"] = meta["duration_s"]
        d.setdefault("qc", {})["lufs"] = meta["loudness"]["input_i"]
        d["version"] = {"built_at": meta["built_at"], "notes": meta["notes"]}
        # same file names, new bytes: a version mark on the link so no browser or edge cache
        # (the site's /media proxy keeps a file a day) plays the old master
        mark = "".join(c for c in meta["built_at"] if c.isdigit())[:12]
        for k in ("audio_url", "video_url"):
            if d.get(k) and "/releases/download/" in d[k]:
                d[k] = f"{d[k].split('?')[0]}?v={mark}"
        if pub:
            # youtube_url stays the Short, as on every robot drop; the full video gets its own field
            d["youtube_url"] = f"https://www.youtube.com/watch?v={pub['short']}"
            d["youtube_full_url"] = f"https://www.youtube.com/watch?v={pub['full']}"
    entry["built"] = {k: meta[k] for k in ("duration_s", "loudness", "built_at", "short")}
    if pub:
        entry["published"] = pub


def remap_channel(channel: dict, pub: dict) -> None:
    """The new uploads inherit the old ones' facts in site/data/channel.json, so retitle knows
    them; the old ids stay, marked replaced."""
    vids = channel.setdefault("videos", {})
    old_full, old_short = pub["replaced"]
    for old, new in ((old_full, pub["full"]), (old_short, pub["short"])):
        if old in vids:
            vids[new] = {**vids[old], **({"full": pub["full"]} if vids[old].get("kind") == "short" else {})}
            vids[old]["replaced_by"] = new


def pending(versions: dict, stage: str) -> list[dict]:
    """Entries not yet through ``stage`` ('built' or 'published')."""
    return [e for e in versions.get("records", []) if stage not in e]


def load(path: Path = VERSIONS_PATH) -> dict:
    return read_json(path, {"records": []}) or {"records": []}


def save(data: dict, path: Path = VERSIONS_PATH) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
