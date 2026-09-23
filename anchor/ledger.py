"""The ledger: one entry per song with every variant tried, every file made, every upload,
and the reason behind each published field. site/data/ledger.json feeds /ops/.

``record`` writes the entry when a drop is made; ``sync`` refreshes the upload rows when
Buffer reports a status or link. Entries the robot did not make (the channel's back
catalogue, fixed by hand) carry ``source: "manual"`` and are never touched here.
"""
from __future__ import annotations

import re
from pathlib import Path

from .config import LEDGER_PATH, Profile
from .seo import MAX_TITLE, genre_phrase
from .unique import AUDIO_MAX_SIMILARITY, COVER_MIN_DISTANCE, SEQUENCE_MAX_SIMILARITY
from .util import iso, read_json, utcnow, write_json

# targets a drop is pushed to, in the order the dashboard shows them
TARGETS = ("youtube_full", "youtube_short", "instagram_reel", "github_release", "site")


def clean_title(title: str) -> str:
    """The channel writes the one swearing title with a star, everywhere."""
    return re.sub(r"\bF(u)cking\b", "F*cking", title or "")


def load(path: Path = LEDGER_PATH) -> dict:
    data = read_json(path, None) or {"entries": []}
    data.setdefault("entries", [])
    return data


def save(ledger: dict, path: Path = LEDGER_PATH) -> None:
    ledger["entries"] = sorted(ledger["entries"], key=lambda e: (e.get("date", ""), e.get("id", "")), reverse=True)
    ledger["updated_at"] = iso(utcnow())
    write_json(path, ledger)


def upsert(ledger: dict, entry: dict) -> dict:
    ledger["entries"] = [e for e in ledger["entries"] if e.get("id") != entry["id"]] + [entry]
    return ledger


def _field(name: str, value, rule: str, evidence: str | None = None, group: str = "content") -> dict:
    return {"field": name, "value": value, "rule": rule, "evidence": evidence, "group": group}


def _variants(meta: dict, catalog: dict | None = None) -> list[dict]:
    """Everything tried before the drop shipped: model attempts, Suno siblings, cover draws."""
    attempts = meta["qc"]["attempts"]
    last = attempts[-1]["attempt"]
    out = []
    for a in attempts:
        near = a.get("nearest_audio") or {}
        out.append({
            "kind": "audio", "label": f"attempt {a['attempt']}" + (f" · {a['source']}" if a.get("source") else ""),
            "seed": a.get("seed"), "ok": bool(a.get("ok")), "chosen": a["attempt"] == last and bool(a.get("ok")),
            "fail": list(a.get("fail") or []), "warn": list(a.get("warn") or []),
            "nearest": near.get("id"), "score": near.get("similarity"), "note": None,
        })
    out.extend(suno_variants(catalog, meta["brief"].get("source_file")))
    for t in (meta.get("art") or {}).get("tries") or []:
        out.append({"kind": "cover", "label": f"cover seed {t['seed']}", "seed": t["seed"], "ok": bool(t["ok"]),
                    "chosen": bool(t["ok"]), "fail": [] if t["ok"] else [f"motif too close to {t['nearest']} ({t['distance']:.0f}/256)"],
                    "warn": [], "nearest": t.get("nearest"), "score": t.get("distance"), "note": None})
    return out


def suno_variants(catalog: dict | None, source_file: str | None) -> list[dict]:
    """The Suno siblings of a queued track (same prompt batch), the one released marked chosen."""
    songs = ((catalog or {}).get("catalogue") or {}).get("songs") or []
    if not source_file or not songs:
        return []
    stem = source_file.rsplit(".", 1)[0]
    mine = next((s for s in songs if stem.endswith(s["id"].split("-")[0])), None)
    if not mine:
        return []
    group = [s for s in songs if s.get("group") == mine.get("group")] or [mine]
    return [{
        "kind": "suno", "label": f"{clean_title(s['title'])} · {s.get('model')} · {s.get('duration_s', 0):.0f} s",
        "seed": s["id"][:8], "ok": bool(s.get("postable")), "chosen": s["id"] == mine["id"],
        "fail": [] if s.get("postable") else [c["label"] for c in s.get("checks", []) if not c.get("ok")],
        "warn": [], "nearest": None, "score": s.get("rating"), "note": s.get("verdict"), "url": s.get("url"),
    } for s in sorted(group, key=lambda s: -(s.get("rating") or 0))]


def _uploads(meta: dict, pub: dict, drop: dict) -> list[dict]:
    files = meta["files"]
    y, ys, ig = pub.get("youtube") or {}, pub.get("youtube_short") or {}, pub.get("instagram") or {}
    status = drop.get("status") or pub.get("status") or "made"
    rows = [
        {"target": "youtube_full", "file": files.get("full_169"), "status": status,
         "url": drop.get("youtube_url") or y.get("external_link"), "post_id": y.get("post_id") or pub.get("post_id"),
         "due_at": y.get("due_at") or pub.get("due_at"), "error": y.get("error") or pub.get("error")},
        {"target": "youtube_short", "file": files.get("short"),
         "status": ("error" if ys.get("error") else drop.get("short_status") or ys.get("status")) or ("not sent" if not ys else None),
         "url": drop.get("youtube_short_url") or ys.get("external_link"), "post_id": ys.get("post_id"),
         "due_at": ys.get("due_at"), "error": ys.get("error")},
        {"target": "instagram_reel", "file": files.get("full_916"),
         "status": ("error" if ig.get("error") else ig.get("status")) or ("not sent" if not ig else None),
         "url": drop.get("instagram_url") or ig.get("external_link"), "post_id": ig.get("post_id"),
         "due_at": ig.get("due_at"), "error": ig.get("error")},
        {"target": "github_release", "file": files.get("mp3"), "status": "released" if drop.get("release_url") else "not released",
         "url": drop.get("release_url"), "post_id": None, "due_at": None, "error": None},
        {"target": "site", "file": files.get("cover_600"), "status": "listed" if drop.get("cover") else "not listed",
         "url": None, "post_id": None, "due_at": None, "error": None},
    ]
    if pub.get("dry_run"):
        for r in rows:
            r["status"] = "dry-run"
    return rows


def _files(meta: dict) -> list[dict]:
    f, v, full = meta["files"], meta.get("video") or {}, meta.get("full") or {}
    f169, f916 = full.get("full_169") or {}, full.get("full_916") or {}
    return [
        {"role": "master", "file": f["mp3"], "spec": f"MP3 320k, ID3 tagged, {meta['loudness']['after']['input_i']} LUFS"},
        {"role": "master (lossless)", "file": f["flac"], "spec": "FLAC, same master"},
        {"role": "short 9:16", "file": f["short"], "spec": f"{v.get('width')}x{v.get('height')} {v.get('fps')} fps, {v.get('duration', 0):.0f} s"},
        {"role": "full video 16:9", "file": f["full_169"], "spec": f"{f169.get('width')}x{f169.get('height')}, {f169.get('duration', 0):.0f} s"},
        {"role": "reel 9:16", "file": f["full_916"], "spec": f"{f916.get('width')}x{f916.get('height')}, {f916.get('duration', 0):.0f} s"},
        {"role": "cover", "file": f["cover"], "spec": "1440x1440 square, type set"},
        {"role": "thumbnail 16:9", "file": f.get("thumbnail"), "spec": "1920x1080 frame, type over the raw art"},
    ]


def _fields(profile: Profile, meta: dict, pub: dict) -> list[dict]:
    b, art, loud, win = meta["brief"], meta["art"], meta["loudness"], meta.get("short_window") or {}
    yt, music = profile.youtube, profile.music
    lane = profile.lane(b["lane"])
    fam = profile.family(b["family"])
    queued = b.get("source") == "queue"
    payload = ((pub.get("payload") or {}).get("youtube") or {}).get("metadata", {}).get("youtube", {})
    attempts = meta["qc"]["attempts"]
    near = (attempts[-1].get("nearest_audio") or {})
    F = []

    # ---- the record
    if queued:
        F.append(_field("source", f"your own track: {b.get('source_file')}", "A track waiting in the queue is released before the model makes one; its title and copy come from the queue file.", None, "record"))
    else:
        F.append(_field("source", f"generated by {meta['engine'].get('engine')}" + (f" ({meta['engine'].get('model')})" if meta['engine'].get('model') else ""),
                        "Nothing queued, so the engine generated the record from the brief.",
                        f"{len(attempts)} attempt(s); chosen seed {b['seed']}", "record"))
    F.append(_field("sound lane", b["lane_name"],
                    "Weighted pick from the profile's lanes: never the lane of the previous drop, lanes used in the last three drops down-weighted. Seeded by the date, so a rerun picks the same lane.",
                    f"lane weight {getattr(lane, 'weight', 1)}; genre line: {b['genre_line']}", "record"))
    bpm_ev = f"asked {b['bpm_requested']} BPM, audio measured {meta['qc']['audio'].get('bpm_est')}" if b.get("bpm_requested") else f"in the lane's range {lane.bpm[0]}-{lane.bpm[1]}; audio measured {meta['qc']['audio'].get('bpm_est')}"
    F.append(_field("bpm", b["bpm"], "Random tempo inside the lane's BPM range; the published tempo follows the audio when the measured tempo differs by more than 1 BPM (the model treats BPM as guidance).", bpm_ev, "record"))
    key_ev = (f"asked {b['key_requested']}, heard {b['key']} (confidence {b.get('key_confidence')})" if b.get("key_requested")
              else f"confidence {b.get('key_confidence', 'n/a')}")
    F.append(_field("key", b["key"], "Random key not used in the last three drops; replaced by the key actually heard in the audio when the detector is confident (>= 0.25). Kept off every public surface.", key_ev, "record"))
    F.append(_field("duration", f"{b['duration_s']} s", "Drawn for the day inside the profile's duration range; every drop is a complete arrangement whose shape is also drawn for the day, so no two records share a timeline.", f"shape {b.get('shape', 'classic')}", "record"))
    F.append(_field("quality gate", "pass" if attempts[-1]["ok"] else "kept despite fails",
                    f"Each attempt must be finite audio at the right length, no dropouts, no clipping, tempo near the brief, and must not resemble a released drop: loudness envelope correlation <= {AUDIO_MAX_SIMILARITY} and spectral-sequence correlation <= {SEQUENCE_MAX_SIMILARITY} against every released master. A fail is regenerated with the next seed.",
                    f"nearest released audio {near.get('id')} at envelope {near.get('envelope', near.get('similarity'))}, spectral sequence {near.get('sequence', 'n/a')}; warnings: {', '.join(meta['qc']['warnings']) or 'none'}", "record"))
    F.append(_field("master loudness", f"{loud['after']['input_i']} LUFS / {loud['after']['input_tp']} dBTP",
                    f"Mastered to {music['loudness_lufs']} LUFS integrated with a {music['true_peak_db']} dBTP ceiling (YouTube plays everything at -14, so the master sits at that level with headroom for the AAC encoder instead of being turned down) and a {music.get('outro_fade_s', 0)} s outro fade.",
                    f"before {loud['before']['input_i']} LUFS; gain {loud.get('gain_db')} dB", "record"))

    # ---- names and copy
    if b.get("hook"):
        F.append(_field("title", b["title"], "A song that sings a hook is named after the hook: the most repeated sung line (>= 2 repeats, <= 10 words), unless that title already exists on the channel.",
                        f"hook {b['hook']!r}" + (f"; word-bank title was {b['title_generated']!r}" if b.get("title_generated") else ""), "content"))
    elif queued:
        F.append(_field("title", b["title"], "Taken from the queued track's own title.", None, "content"))
    else:
        F.append(_field("title", b["title"], "Drawn from the title word bank: never repeats a title on the channel, avoids every word used in the last ten titles, never doubles a word. Seeded by the date.", "no sung hook found", "content"))
    F.append(_field("youtube title", b["youtube_title"],
                    "The track's name and nothing else: YouTube prints the channel name under every title, the description carries genre and tempo, and a phone shows about 50 characters.",
                    f"{len(b['youtube_title'])} chars; genre phrase {genre_phrase(lane)!r}", "content"))
    copy = b.get("copy") or {}
    F.append(_field("description", b["description"],
                    "The vibe and the theme of the record in two to four sentences that build like an intro, nothing mechanical (no timestamps, no tempo, no section names); then genre · BPM · artist, the playlist, site and Instagram, the AI disclosure, ©, three hashtags. About 400 characters, because a phone shows two lines. Gemini writes it from the brief's mood and theme and any clock time or hype word is rejected; the template writes it when there is no key.",
                    f"written by {copy.get('source', 'template')}; arc: {len((b.get('arc') or {}).get('drops', []))} drop(s), {len((b.get('arc') or {}).get('breakdowns', []))} breakdown(s); mood: {b.get('mood')!r}", "content"))
    F.append(_field("tags", b["tags"],
                    "Lane tags first (the niche), then the channel's base tags, the genre phrase, '<BPM> bpm techno', the year, 'ai techno' and 'techno full track'; duplicates removed, order kept so the most specific tags lead.",
                    f"{len(b['tags'])} tags", "content"))
    F.append(_field("instagram caption", b.get("caption_instagram"),
                    "The same copy as YouTube, the genre line, the site link, then the channel's Instagram hashtag set (broader than YouTube's three).", None, "content"))

    # ---- platform settings
    F.append(_field("category", "Music (10)", "YouTube category id from the profile; every drop is a song.", f"sent as categoryId {payload.get('categoryId', yt['category_id'])}", "platform"))
    F.append(_field("privacy", yt["privacy"], "Public on publish; Buffer schedules the post for the drop's slot.", None, "platform"))
    F.append(_field("AI disclosure", "on", "YouTube 'altered or synthetic content' flag and Instagram AI label are always on: the audio is model-generated and the channel says so in every description too.", f"isAiGenerated={payload.get('isAiGenerated', True)}", "platform"))
    F.append(_field("made for kids", "no", "Club music for adults; never marked for kids (which would strip comments, end screens and personalised ads).", None, "platform"))
    F.append(_field("notify subscribers", "yes" if yt["notify_subscribers"] else "no", "Subscribers get the bell on every drop; the cadence is every second day, so it never spams.", None, "platform"))
    F.append(_field("licence", "Standard YouTube licence", "Standard, not Creative Commons: the channel keeps its rights; the © line in the description says the same.", "set in the channel's upload defaults", "platform"))
    F.append(_field("language", "English", "Title and description language and video language both English (channel default), so YouTube can index and translate the copy.", None, "platform"))
    F.append(_field("post time", b["post_at"],
                    f"{profile.schedule['post_time_utc']} UTC ({'23:00' if profile.schedule['post_time_utc'] == '17:30' else profile.schedule['post_time_utc']} IST): late-evening India, afternoon Europe, morning US - the widest awake techno audience. One drop every {profile.schedule.get('every_days', 1)} day(s) from {profile.schedule.get('anchor_date')}.",
                    None, "platform"))

    # ---- visuals
    F.append(_field("visual family", f"{b['family_name']} ({fam.accent})", "One of the profile's palettes, never one used in the last three drops, so consecutive covers read differently on the channel grid.", None, "visual"))
    src = art.get("source")
    F.append(_field("cover", src, ("Cloudflare Flux image from the family prompt, seeded by the date" if src != "procedural" else "Procedural art drawn from the family's forms and the date seed") +
                    f"; redrawn from the next seed until it is at least {COVER_MIN_DISTANCE}/256 away from every cover already on the site.",
                    f"nearest existing cover {(art.get('nearest') or {}).get('id')} at distance {(art.get('nearest') or {}).get('distance')}" + (f"; fallback because {art['fallback_reason']}" if art.get("fallback_reason") else ""), "visual"))
    F.append(_field("thumbnail 16:9", meta["files"].get("thumbnail"), "Drawn for the phone: the title in Anton at up to 300 px on a left scrim, the lane and BPM under it at 90 px, hard shadow; no wordmark, because the channel name is printed under the thumbnail anyway. Legible at the 336×189 px a phone shows.", None, "visual"))
    F.append(_field("short window", f"{win.get('start_s', 0):.1f} s for {win.get('length_s', 0):.1f} s",
                    f"The loudest, busiest {b['short_s']} s of the master snapped to whole bars, with the pulse locked to the beat grid of that cut.", f"beat offset {win.get('beat_offset_s')} s", "visual"))
    return F


def build_entry(profile: Profile, meta: dict, pub: dict, drop: dict, catalog: dict | None = None) -> dict:
    b = meta["brief"]
    return {
        "id": b["id"], "date": b["date"], "title": clean_title(b["title"]), "source": "pipeline",
        "made_at": meta.get("made_at"), "recorded_at": iso(utcnow()),
        "lane": b["lane_name"], "bpm": b["bpm"], "family": b["family_name"], "accent": profile.family(b["family"]).accent,
        "cover": drop.get("cover"),
        "engine": {"name": meta["engine"].get("engine"), "model": meta["engine"].get("model"),
                   "render_s": meta["engine"].get("total_s"), "fallback_from": meta["engine"].get("fallback_from")},
        "variants": _variants(meta, catalog),
        "files": _files(meta),
        "uploads": _uploads(meta, pub, drop),
        "fields": _fields(profile, meta, pub),
    }


def refresh(ledger: dict, catalog: dict) -> int:
    """Copy the latest status / links from the catalog into the upload rows. Returns rows changed."""
    by_id = {d["id"]: d for d in catalog.get("drops", [])}
    changed = 0
    for e in ledger["entries"]:
        d = by_id.get(e["id"])
        if not d or e.get("source") != "pipeline":
            continue
        for row in e["uploads"]:
            new = None
            if row["target"] == "youtube_full":
                new = {"status": d.get("status") or row["status"], "url": d.get("youtube_url") or row["url"], "error": d.get("error")}
            elif row["target"] == "youtube_short" and (d.get("short_status") or d.get("youtube_short_url")):
                new = {"status": d.get("short_status") or row["status"], "url": d.get("youtube_short_url") or row["url"]}
            elif row["target"] == "instagram_reel" and d.get("instagram_url"):
                new = {"url": d["instagram_url"]}
            if new and any(row.get(k) != v for k, v in new.items()):
                row.update(new)
                changed += 1
    return changed


def problems(ledger: dict) -> list[str]:
    """What ``anchor check`` verifies about the ledger."""
    out = []
    ids = [e.get("id") for e in ledger.get("entries", [])]
    if len(ids) != len(set(ids)):
        out.append("duplicate ids in ledger")
    for e in ledger.get("entries", []):
        for key in ("id", "date", "title", "source", "uploads", "fields"):
            if e.get(key) in (None, "", []):
                out.append(f"ledger {e.get('id')}: missing {key}")
        for f in e.get("fields", []):
            if not f.get("rule"):
                out.append(f"ledger {e.get('id')}: field {f.get('field')} has no rule")
    return out
