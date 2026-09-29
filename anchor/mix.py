"""The weekly and monthly mix: the period's releases as one continuous set.

Why: on 2026-09-23 every breakout video in this niche from a channel under 6k subscribers
was a 30 to 70 minute mix with a keyword-led title; single 150-second tracks with a bare
name got ten views. A mix is the watch-time asset that lets YouTube suggest the channel.

How: the period's masters, ordered by tempo so the set climbs, each matched to -14 LUFS,
joined with equal-power crossfades of eight bars at the outgoing tempo, the incoming record
entering on a downbeat of its own grid. No time-stretching: the tempos of one week sit
within a few BPM of each other and a hard cut between 130 and 155 reads as a DJ's gear
change, which is what a hard techno set does. Chapters in the description give every
track its name and a seekable start. One mix is never the same twice: the tracks are new
every week, and the monthly is the month's drops end to end.
"""
from __future__ import annotations

import urllib.request
from datetime import date as Date, timedelta
from pathlib import Path

import numpy as np

from .art import make_cover
from .audio import SR, beat_phase, decode, encode_mp3, loudness, master
from .config import Profile
from .ledger import clean_title
from .music import write_wav
from .seo import genre_phrase
from .util import iso, log, utcnow, write_json
from .video import frame_169, render_motion

CROSSFADE_BARS = 8
TARGET_LUFS = -14.0
SILENCE_DB = -45.0


def period_window(day: str, period: str) -> tuple[str, str]:
    """(first day, last day) inclusive: the seven days ending on ``day``, or its calendar month."""
    d = Date.fromisoformat(day)
    if period == "month":
        first = d.replace(day=1)
        return first.isoformat(), d.isoformat()
    return (d - timedelta(days=6)).isoformat(), d.isoformat()


def pick_tracks(catalog: dict, day: str, period: str) -> list[dict]:
    """The period's released drops that have a master to download, oldest first."""
    lo, hi = period_window(day, period)
    drops = [d for d in catalog.get("drops", []) if lo <= d.get("date", "") <= hi and d.get("audio_url")
             and d.get("status") in ("sent", "scheduled", "released", "buffer", "public", None)]
    return sorted(drops, key=lambda d: d["date"])


def volume_number(catalog: dict, period: str) -> int:
    return 1 + sum(1 for m in catalog.get("mixes", []) if m.get("period") == period)


def fetch(drops: list[dict], work: Path) -> list[dict]:
    work.mkdir(parents=True, exist_ok=True)
    out = []
    for d in drops:
        f = work / f"{d['id']}.mp3"
        if not f.exists():
            urllib.request.urlretrieve(d["audio_url"], f)
        out.append({**d, "file": f})
    return out


def _trim(audio: np.ndarray, sr: int = SR, floor_db: float = SILENCE_DB) -> np.ndarray:
    """Cut the silence either side, so the crossfade meets music, not padding."""
    env = np.abs(audio).max(axis=1)
    thresh = 10 ** (floor_db / 20)
    idx = np.nonzero(env > thresh)[0]
    if len(idx) == 0:
        return audio
    return audio[idx[0]: idx[-1] + 1]


def _gain_to(path: Path, target: float = TARGET_LUFS) -> float:
    measured = loudness(path)["input_i"]
    return 10 ** ((target - measured) / 20)


def join(tracks: list[dict], sr: int = SR, bars: int = CROSSFADE_BARS) -> tuple[np.ndarray, list[dict]]:
    """Crossfade the ordered tracks into one array. Returns (audio, chapters with start_s)."""
    out: np.ndarray | None = None
    chapters = []
    prev_bpm = None
    for t in tracks:
        audio = _trim(decode(t["file"])) * _gain_to(t["file"])
        bpm = float(t["bpm"])
        # the incoming record starts on its own downbeat
        phase = beat_phase(audio.mean(axis=1), bpm, sr)
        audio = audio[int(phase * sr):]
        if out is None:
            out, start = audio, 0.0
        else:
            fade = int(bars * 4 * 60.0 / prev_bpm * sr)
            fade = min(fade, len(out) // 2, len(audio) // 2)
            ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)[:, None]
            head, tail = out[:-fade], out[-fade:]
            mixed = tail * np.sqrt(1.0 - ramp) + audio[:fade] * np.sqrt(ramp)   # equal power
            start = len(head) / sr
            out = np.concatenate([head, mixed, audio[fade:]])
        chapters.append({"id": t["id"], "title": clean_title(t["title"]), "bpm": int(bpm), "lane": t.get("lane"), "start_s": round(start, 2)})
        prev_bpm = bpm
    return out if out is not None else np.zeros((sr, 2), dtype=np.float32), chapters


def stamp(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def words(profile: Profile, chapters: list[dict], period: str, vol: int, duration_s: float, day: str) -> dict:
    """Title, description with chapters, tags. The title leads with the search phrase."""
    name = profile.artist["name"]
    site = profile.artist["site_url"].removeprefix("https://").rstrip("/")
    yt = profile.youtube
    known = {l.id: l for l in profile.lanes}
    lanes = [known.get(c.get("lane")) for c in chapters]
    phrases = list(dict.fromkeys(genre_phrase(l) for l in lanes if l))
    lead = phrases[0] if phrases else "Hard Techno"
    year = day[:4]
    minutes = int(round(duration_s / 60))
    kind = "Monthly Mix" if period == "month" else "Mix"
    title = f"{lead} {kind} {year} | {name} Vol. {vol} | {len(chapters)} tracks, {minutes} min, 150+ BPM warehouse rave"
    if len(title) > 100:
        title = f"{lead} {kind} {year} | {name} Vol. {vol} | {minutes} min"
    lines = [f"{lead} mix, {minutes} minutes, {len(chapters)} original {name} tracks back to back. "
             f"{'The month' if period == 'month' else 'The week'} in one set, in tempo order. Free downloads of every track below.", "",
             "Tracklist"]
    lines += [f"{stamp(c['start_s'])} {c['title']} ({c['bpm']} BPM)" for c in chapters]
    lines += ["", f"All tracks: {yt.get('playlist_url', site)}", f"Free download: {site} · IG @{profile.artist.get('instagram_handle', '').lstrip('@')}",
              "Made with AI music tools and my own hours. AI use disclosed.", f"© {year} {name}", "",
              " ".join(dict.fromkeys(["#hardtechno", "#technomix", *[f"#{p.lower().replace(' ', '')}" for p in phrases[:2]]]))]
    tags = list(dict.fromkeys([f"{lead.lower()} mix", "hard techno mix", f"techno mix {year}", f"hard techno mix {year}",
                               "industrial techno", "dark techno mix", "rave music", "berlin techno", "peak time techno",
                               *[genre_phrase(l).lower() for l in lanes if l], *yt.get("base_tags", [])]))
    return {"title": title[:100], "description": "\n".join(lines), "tags": tags[:40]}


def build(profile: Profile, catalog: dict, day: str, period: str, out_dir: Path, *, art_mode: str | None = None,
          crf: int = 28) -> dict:
    """Everything for one mix: audio, cover, 16:9 video, words, meta.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    drops = pick_tracks(catalog, day, period)
    if len(drops) < 3:
        raise RuntimeError(f"only {len(drops)} released track(s) in the {period} ending {day}; a mix needs three")
    tracks = sorted(fetch(drops, out_dir / "tracks"), key=lambda d: (int(d["bpm"]), d["date"]))
    vol = volume_number(catalog, period)
    audio, chapters = join(tracks)
    raw = out_dir / "mix_raw.wav"
    write_wav(raw, audio)
    master_wav = out_dir / "mix.wav"
    loud = master(raw, master_wav, float(profile.music.get("loudness_lufs", TARGET_LUFS)),
                  float(profile.music.get("true_peak_db", -1.5)))
    duration_s = len(audio) / SR
    base = f"{profile.artist['name']}-{period}-mix-{day}-vol-{vol}"
    mp3 = out_dir / f"{base}.mp3"
    w = words(profile, chapters, period, vol, duration_s, day)
    # the cover: the newest track's family, a fresh procedural draw, typed for the mix
    fams = {f.id: f for f in profile.families}
    fam = fams.get(tracks[-1].get("family")) or profile.families[0]
    seed = int(tracks[-1].get("seed") or 1) + vol
    art = make_cover(fam, {"title": f"Mix Vol. {vol}", "seed": seed}, profile.artist["name"], out_dir, art_mode or "procedural")
    encode_mp3(master_wav, mp3, tags={"title": w["title"].split(" | ")[0] + f" Vol. {vol}", "artist": profile.artist["name"],
                                      "album": f"{profile.artist['name']} mixes", "date": day, "genre": "Techno"},
               cover=out_dir / "cover_600.jpg")
    lead = w["title"].split(" Mix")[0].split(" Monthly")[0]
    lane_phrase = f"{lead} · {len(chapters)} tracks · {int(round(duration_s / 60))} min"
    frame = frame_169(out_dir / "cover_art_raw.jpg", {"title": f"{'Monthly ' if period == 'month' else ''}Mix Vol. {vol}"},
                      lane_phrase, profile.artist["name"], out_dir / "frame-169.jpg", fam.accent)
    video = out_dir / f"{base}-full-169.mp4"
    info = render_motion(frame, mp3, video, fam.accent, crf=crf, timeout=5400)
    meta = {"kind": "mix", "period": period, "vol": vol, "date": day, "window": period_window(day, period),
            "title": w["title"], "description": w["description"], "tags": w["tags"],
            "chapters": chapters, "duration_s": round(duration_s, 1), "loudness": loud, "art": art,
            "files": {"base": base, "mp3": mp3.name, "full_169": video.name, "thumbnail": "frame-169.jpg",
                      "cover": "cover.jpg", "cover_600": "cover_600.jpg"},
            "video": info, "made_at": iso(utcnow())}
    write_json(out_dir / "meta.json", meta)
    log(f"mix: {w['title']!r}: {len(chapters)} tracks, {duration_s / 60:.1f} min, {loud['after']['input_i']} LUFS")
    return meta


def record(catalog: dict, meta: dict, pub: dict | None, repo: str | None) -> dict:
    """The mix's row in the catalog (site/data/catalog.json['mixes'])."""
    tag = f"mix-{meta['period']}-{meta['date']}"
    files = meta["files"]
    y = (pub or {}).get("youtube") or {}
    row = {"id": tag, "period": meta["period"], "vol": meta["vol"], "date": meta["date"], "title": meta["title"],
           "tracks": [c["id"] for c in meta["chapters"]], "duration_s": meta["duration_s"],
           "audio_url": f"https://github.com/{repo}/releases/download/{tag}/{files['mp3']}" if repo else None,
           "video_url": f"https://github.com/{repo}/releases/download/{tag}/{files['full_169']}" if repo else None,
           "cover": f"covers/{tag}.jpg", "youtube_url": y.get("external_link"), "post_id": y.get("post_id"),
           "status": y.get("status") or ("error" if (pub or {}).get("error") else "made"), "created_at": meta["made_at"]}
    mixes = [m for m in catalog.get("mixes", []) if m.get("id") != tag] + [row]
    catalog["mixes"] = sorted(mixes, key=lambda m: m["date"], reverse=True)
    return row
