"""BPM-free thumbnails for every video already on the channel.

The older full videos and Shorts were drawn with the tempo under the title ("RAWSTYLE HYBRID .
155 BPM"). Every listener surface is tempo-free now, so each public video that still carries an
old thumbnail gets a new one drawn from the song's own artwork: the title and the genre from the
video's (already tempo-free) title, nothing else. 16:9 for a full video, 9:16 for a Short.

Runs inside the Uploads job (50 API units per thumbnail). The ids it has redrawn are kept in
``uploads.json`` under ``thumbs`` so a video is redrawn once; a quota error stops the pass and the
rest follow on the next run. Motion videos (the MARK line) already have a tempo-free frame.
"""
from __future__ import annotations

import re
import urllib.request
from pathlib import Path

from .config import CATALOG_PATH, FONTS, SITE
from .util import log, read_json

MAX_PER_RUN = 60          # 3,000 units at most, so the day's uploads still fit in 10,000


def _key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.split(" | ")[0].lower())


def genre_of(title: str) -> str:
    """'Cold Bunker | Rawstyle Hybrid | ANCHOR' -> 'Rawstyle Hybrid' (no tempo in it, ever)."""
    parts = [p.strip() for p in title.split(" | ")]
    g = parts[1] if len(parts) > 2 else "Techno"
    return re.sub(r"\s*[-.·]?\s*\d{2,3}\s*BPM\b", "", g, flags=re.I).strip() or "Techno"


def sources(repo: str, catalog_path: Path = CATALOG_PATH) -> dict[str, dict]:
    """Song name key -> where its artwork is: the catalogue, the older songs, and the one-off
    uploads (their release keeps a ``-cover.jpg`` next to the video)."""
    out: dict[str, dict] = {}
    data = catalog_path.parent
    for d in (read_json(catalog_path, {}) or {}).get("drops", []):
        if d.get("cover"):
            out.setdefault(_key(d["title"]), {"path": str(SITE / d["cover"]), "accent": d.get("accent")})
    for d in (read_json(data / "legacy_motion.json", {}) or {}).get("songs", []):
        if d.get("cover"):
            out.setdefault(_key(d["title"]), {"path": str(SITE / d["cover"]), "accent": d.get("accent")})
    for e in (read_json(data / "uploads.json", {}) or {}).get("uploads", []):
        m = re.match(r"(ANCHOR-\d{4}-\d{2}-\d{2}-[a-z0-9-]+?)-(full-169|short|motion-full-169)\.mp4$", e.get("file", ""))
        if m and e.get("release", "").startswith("drop-"):
            out.setdefault(_key(e["title"]), {"url": f"https://github.com/{repo}/releases/download/{e['release']}/{m[1]}-cover.jpg"})
    return out


def is_short(video_id: str) -> bool:
    """youtube.com/shorts/<id> answers 200 for a Short and redirects to /watch for anything else."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(urllib.request.Request(f"https://www.youtube.com/shorts/{video_id}", method="HEAD"), timeout=20) as r:
            return r.status == 200
    except Exception:                     # noqa: BLE001 - a redirect raises here: not a Short
        return False


def short_frame(cover: Path, title: str, genre: str, out: Path, accent: str = "#ff3bd4") -> Path:
    """The Short's 9:16 thumbnail: the hologram art, the title over it, the genre under it."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    from .video import HOLO, _rgb, frame_916
    frame_916(cover, out, accent)
    im = Image.open(out).convert("RGBA")
    W = im.width
    d = ImageDraw.Draw(im)

    def font(size):
        return ImageFont.truetype(str(FONTS / "Anton.ttf"), size)
    words, lines = title.upper().split(), []
    size = 170
    while size > 90:
        lines, cur = [], ""
        for w in words:
            t = f"{cur} {w}".strip()
            if d.textlength(t, font=font(size)) <= W - 120:
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        if len(lines) <= 3 and all(lines):
            break
        size -= 10
    f, fs = font(size), font(72)
    glow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ink = Image.new("RGBA", im.size, (0, 0, 0, 0))
    gd, idr = ImageDraw.Draw(glow), ImageDraw.Draw(ink)
    y = 90
    for ln in lines:
        x = (W - d.textlength(ln, font=f)) / 2
        gd.text((x, y), ln, font=f, fill=(*HOLO, 255))
        idr.text((x, y), ln, font=f, fill=(240, 254, 255, 255))
        y += int(size * 1.0)
    g = genre.upper()
    x = (W - d.textlength(g, font=fs)) / 2
    gd.text((x, y + 16), g, font=fs, fill=(*_rgb(accent), 255))
    idr.text((x, y + 16), g, font=fs, fill=(*_rgb(accent), 255))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)))
    im.alpha_composite(ink)
    im.convert("RGB").save(out, quality=90)
    return out


def draw(src: dict, title: str, short: bool, work: Path, artist: str) -> Path:
    from .video import frame_169
    work.mkdir(parents=True, exist_ok=True)
    k = _key(title)
    cover = work / f"{k}-cover.jpg"
    if src.get("url"):
        urllib.request.urlretrieve(src["url"], cover)
    else:
        cover.write_bytes(Path(src["path"]).read_bytes())
    name, genre, accent = title.split(" | ")[0].strip(), genre_of(title), src.get("accent") or "#ff3bd4"
    out = work / f"{k}-{'short' if short else 'full'}-thumb.jpg"
    if short:
        return short_frame(cover, name, genre, out, accent)
    return frame_169(cover, {"title": name}, genre, artist, out, accent)


def run(api, videos: list[dict], data: dict, repo: str, work: Path, artist: str, mark: str,
        max_sets: int = MAX_PER_RUN, short_test=is_short, catalog_path: Path = CATALOG_PATH) -> list[str]:
    """Redraw the thumbnail of every public video that still has an old (tempo) one."""
    done = data.setdefault("thumbs", [])
    src = sources(repo, catalog_path)
    changed: list[str] = []
    for v in videos:
        if len(changed) >= max_sets:
            break
        if v["id"] in done or v.get("privacy", "public") != "public" or mark.lower() in (v.get("description") or "").lower():
            continue
        s = src.get(_key(v["title"]))
        if not s:
            continue
        try:
            img = draw(s, v["title"], short_test(v["id"]), work, artist)
            api.set_thumbnail(v["id"], img)
        except Exception as exc:          # noqa: BLE001 - quota: the rest follow tomorrow
            log(f"thumbs: {v['id']} {v['title']!r}: {str(exc)[:160]}")
            if "quota" in str(exc).lower():
                break
            continue
        done.append(v["id"])
        changed.append(v["id"])
    if changed:
        log(f"thumbs: tempo-free thumbnail on {len(changed)} video(s): {', '.join(changed)}")
    return changed

