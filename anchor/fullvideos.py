"""Every Short on the channel has its full track on the channel as a video.

``plan`` reads the channel (Data API) and the catalog and sorts every public Short into:
``linked`` (the catalog already names its full video), ``found`` (a full-length upload with the
same name is already on the channel: the catalog gets its link), ``todo`` (no full video yet, and
the song is on file: build and upload it) and ``no_audio`` (no full video and no song on file:
only its owner can supply the track). ``run`` does the found and todo work, at most ``limit``
uploads a run (each upload costs 1,600 of the channel's 10,000 daily API units), records each
link in the catalog as it lands, so a stopped run never uploads a track twice, and puts the
full track's link on its Short.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import seo
from .config import CATALOG_PATH, SITE, Profile
from .ledger import clean_title
from .util import log, read_json, write_json
from .versions import RELEASES, fetch
from .video import frame_169, render_motion
from .youtube import YouTube, playlist_id

SHORT_MAX_S = 70          # the robot's Shorts are 45 s; a full track is two minutes or more
FOOTER = re.compile(r"^(https?://|full track:|all tracks:|free download|full catalogue:|made with|©|#)", re.I)


def seconds(iso_duration: str | None) -> int:
    """'PT2M34S' -> 154."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def video_id(url: str | None) -> str | None:
    if not url:
        return None
    return url.split("?v=")[-1].split("&")[0] if "?v=" in url else url.rstrip("/").rsplit("/", 1)[-1]


def key(title: str) -> str:
    """The track's name alone, for matching: 'Rupture Pulse | Industrial ... | ANCHOR' -> 'rupturepulse'."""
    return re.sub(r"[^a-z0-9]", "", clean_title(title.split("|")[0]).lower())


def records(catalog: dict, channel: dict | None = None) -> list[dict]:
    """Robot drops first, then the hand-made Shorts the site lists, then any other hand-made
    Short site/data/channel.json knows."""
    out = [*catalog.get("drops", []), *[{**l, "legacy": True} for l in catalog.get("legacy", [])]]
    seen = {video_id(r.get("youtube_url")) for r in out}
    for vid, v in ((channel or {}).get("videos") or {}).items():
        if v.get("kind") == "short" and vid not in seen:
            out.append({"title": v["title"], "youtube_url": f"https://www.youtube.com/watch?v={vid}",
                        "youtube_full_url": v.get("full_url"), "legacy": True, "channel": True})
    return out


def plan(catalog: dict, videos: list[dict], channel: dict | None = None) -> dict:
    public = {v["id"]: v for v in videos if v.get("privacy") == "public"}
    shorts = {video_id(r.get("youtube_url")) for r in records(catalog, channel)} - {None}
    fulls: dict[str, list[dict]] = {}
    for v in public.values():
        if v["id"] not in shorts and seconds(v.get("duration")) > SHORT_MAX_S:
            fulls.setdefault(key(v["title"]), []).append(v)
    out = {"linked": [], "found": [], "todo": [], "no_audio": [], "not_public": []}
    for r in records(catalog, channel):
        sid = video_id(r.get("youtube_url"))
        if not sid:
            continue
        if sid not in public:
            out["not_public"].append(r)
        elif r.get("youtube_full_url"):
            out["linked"].append(r)
        elif fulls.get(key(r["title"])):
            out["found"].append((r, fulls[key(r["title"])][0]))
        elif r.get("audio_url"):
            out["todo"].append(r)
        else:
            out["no_audio"].append(r)
    return out


def short_body(description: str) -> str | None:
    """The record's own words from its Short: the first paragraph that is not the search line,
    a link, the footer or hashtags."""
    for para in re.split(r"\n\s*\n", description or ""):
        lines = [l.strip() for l in para.strip().split("\n") if l.strip()]
        if not lines or any(FOOTER.match(l) for l in lines):
            continue
        if re.search(r" BPM\. An \S+ original", lines[0]) or re.fullmatch(r".+ · .+", lines[0]):
            continue
        text = " ".join(lines)
        if len(text.split()) >= 4:          # a sentence, not a stray title or label
            return text
    return None


def lane_of(profile: Profile, r: dict):
    """The record's lane, or None for a hand-made Short or a lane since retired."""
    try:
        return profile.lane(r.get("lane") or "")
    except KeyError:
        return None


def words(profile: Profile, r: dict, short: dict | None) -> tuple[str, str, list[str]]:
    """Title, description and tags in the channel's form for the full track."""
    name = clean_title(r["title"])
    bpm = int(r["bpm"]) if r.get("bpm") else None
    lane = lane_of(profile, r)
    body = short_body((short or {}).get("description", "")) or f"{name}. The full track, start to finish."
    if lane is None or not bpm:
        artist = profile.artist["name"]
        return name, f"{body}\n\nAn {artist} original. AI use disclosed.", list(profile.youtube.get("base_tags", []))
    brief = {"title": name, "lane": r["lane"], "bpm": bpm, "date": r.get("date"), "copy": {"body": body}}
    return (seo.youtube_title(name, lane, bpm, profile.artist["name"]), seo.description(profile, brief, "youtube"),
            seo.tags(profile, lane, bpm))


def raw_art(profile: Profile, r: dict, cover: Path, out: Path) -> Path | None:
    """The cover's artwork without its type, redrawn from the recorded family and seed, so the
    16:9 frame sets its own title over clean art as on every other full track. Only returned
    when it redraws the released cover (a drop whose cover was redrawn used seed + 1..5)."""
    if r.get("art_source") != "procedural" or not r.get("family") or r.get("seed") is None:
        return None
    from PIL import Image, ImageChops, ImageStat
    from .art import finish, procedural
    try:
        fam = profile.family(r["family"])
    except KeyError:
        return None
    released = Image.open(cover).convert("RGB").resize((256, 256))
    for bump in range(6):
        seed = (int(r["seed"]) + bump) % 2_147_483_647
        base = procedural(fam, seed)
        again = finish(base, r["title"], profile.artist["name"], fam, seed).convert("RGB").resize((256, 256))
        if max(ImageStat.Stat(ImageChops.difference(released, again)).mean) < 8:
            base.save(out, quality=92)
            return out
    return None


def plain_art(cover: Path, out: Path) -> Path:
    """When the artwork cannot be redrawn: the cover blurred past its type, so no half-cropped
    title shows behind the frame's own."""
    from PIL import Image, ImageEnhance, ImageFilter
    img = Image.open(cover).convert("RGB").resize((1920, 1920), Image.LANCZOS).filter(ImageFilter.GaussianBlur(48))
    ImageEnhance.Brightness(img).enhance(0.8).save(out, quality=92)
    return out


def build(profile: Profile, r: dict, repo: str, work: Path) -> tuple[Path, Path]:
    """The full 16:9 video from the released master and cover: the same frame and moving
    waveform as every full track the robot uploads."""
    work.mkdir(parents=True, exist_ok=True)
    audio_url = r["audio_url"].split("?")[0]
    base = audio_url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    mp3 = fetch(audio_url, work / f"{base}.{audio_url.rsplit('.', 1)[-1]}")
    try:
        cover = fetch(RELEASES.format(repo=repo, tag=f"drop-{r['id']}", file=f"{base}-cover.jpg"),
                      work / f"{base}-cover.jpg", 20_000)
    except (OSError, RuntimeError, KeyError):
        local = SITE / (r.get("cover") or "")
        if not r.get("cover") or not local.exists():
            raise RuntimeError(f"{r['title']}: no cover on file")
        cover = local
    lane = lane_of(profile, r)
    phrase = seo.genre_phrase(lane) if lane else (r.get("lane_name") or "Techno")
    art = raw_art(profile, r, cover, work / f"{base}-art-raw.jpg") or plain_art(cover, work / f"{base}-art-plain.jpg")
    frame = frame_169(art, {"title": clean_title(r["title"]), "bpm": r.get("bpm")}, phrase,
                      profile.artist["name"], work / f"{base}-frame-169.jpg")
    video = work / f"{base}-full-169.mp4"
    render_motion(frame, mp3, video, r.get("accent") or "#d8742f", crf=23, timeout=3600)
    return video, frame


def link_short(api, short: dict, full_url: str) -> bool:
    """The Short's description points at its full track; True when it had to change."""
    desc = short.get("description", "")
    if full_url in desc:
        return False
    if "Full track:" in desc:
        desc = re.sub(r"Full track: \S+", f"Full track: {full_url}", desc, count=1)
    else:
        paras = desc.split("\n\n")
        paras.insert(min(2, len(paras)), f"Full track: {full_url}")
        desc = "\n\n".join(paras)
    api.update_video(short, title=short["title"], description=desc)
    return True


def run(profile: Profile, *, repo: str, work: Path, limit: int = 2, api=None,
        catalog_path: Path = CATALOG_PATH, channel_path: Path | None = None, dry_run: bool = False) -> dict:
    api = api or YouTube()
    channel_path = channel_path or catalog_path.parent / "channel.json"
    catalog = read_json(catalog_path, {}) or {}
    channel = read_json(channel_path, {}) or {}
    videos = api.channel_videos(profile.artist["youtube_channel_id"])
    by_id = {v["id"]: v for v in videos}
    p = plan(catalog, videos, channel)
    done = {"linked_existing": [], "uploaded": [], "no_audio": [r["title"] for r in p["no_audio"]],
            "left": [], "errors": []}
    if dry_run:
        done["found"] = [f"{r['title']} -> {v['id']}" for r, v in p["found"]]
        done["left"] = [r["title"] for r in p["todo"]]
        return done

    def save(r: dict, url: str) -> None:
        """After every record, so a stopped run never repeats an upload."""
        r["youtube_full_url"] = url
        if r.get("channel"):
            channel["videos"][video_id(r["youtube_url"])]["full_url"] = url
            channel_path.write_text(json.dumps(channel, indent=1, ensure_ascii=False))   # the file's own layout
            return
        target = next((d for d in catalog.get("legacy" if r.get("legacy") else "drops", [])
                       if d.get("youtube_url") == r.get("youtube_url")), None)
        if target is not None:
            target["youtube_full_url"] = url
        write_json(catalog_path, catalog)

    for r, v in p["found"]:
        url = f"https://www.youtube.com/watch?v={v['id']}"
        save(r, url)
        link_short(api, by_id[video_id(r["youtube_url"])], url)
        done["linked_existing"].append(f"{r['title']} -> {v['id']}")
    for i, r in enumerate(p["todo"]):
        if i >= limit:
            done["left"] = [x["title"] for x in p["todo"][i:]]
            break
        short = by_id[video_id(r["youtube_url"])]
        try:
            video, frame = build(profile, r, repo, work / (r.get("id") or key(r["title"])))
            title, description, tags = words(profile, r, short)
            up = api.upload(video, title=title, description=description, tags=tags,
                            category_id=str(profile.youtube["category_id"]), privacy="public",
                            ai_generated=bool(profile.youtube["ai_generated"]), notify=False)
        except Exception as exc:          # noqa: BLE001 - one record's failure never stops the rest
            log(f"fullvideos: {r['title']}: {exc}")
            done["errors"].append(f"{r['title']}: {str(exc)[:300]}")
            continue
        url = f"https://www.youtube.com/watch?v={up['id']}"
        save(r, url)
        for step, fn in (("thumbnail", lambda: api.set_thumbnail(up["id"], frame)),
                         ("playlist", lambda: api.add_to_playlist(up["id"], playlist_id(profile.youtube.get("playlist_url")))
                          if playlist_id(profile.youtube.get("playlist_url")) else None),
                         ("short link", lambda: link_short(api, short, url))):
            try:
                fn()
            except Exception as exc:      # noqa: BLE001 - cosmetic legs, logged
                log(f"fullvideos: {r['title']}: {step} failed: {exc}")
        done["uploaded"].append(f"{r['title']} -> {up['id']}")
    log(f"fullvideos: {len(done['uploaded'])} uploaded, {len(done['linked_existing'])} linked, "
        f"{len(done['left'])} left for the next run, {len(done['no_audio'])} need the full song")
    return done
