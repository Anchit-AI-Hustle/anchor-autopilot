"""Redraw the YouTube thumbnail of a released song whose thumbnail came too close to another one
(2026-11-27: Dig Until Daylight, 2026-11-22, was 80 of 256 from 2026-10-28-2, under the limit of 84).

The new picture is drawn from the song's own released master (anchor/soundart.py, the next redraw
variant that clears every thumbnail already out), stored in site/thumbs (480 px, what the gate
compares with) and site/thumbs/full (the 1280 px frame YouTube gets). The video is queued in
site/data/uploads.json "thumb_fixes"; the Uploads job sets it on YouTube (anchor/thumbs.py fixes).
Nothing needs a secret here: the audio comes from the public release.

    python scripts/thumb_fix.py 2026-11-22
"""
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from anchor import genres as genremod, soundart          # noqa: E402
from anchor.audio import SR, decode                       # noqa: E402
from anchor.seo import genre_phrase                      # noqa: E402
from anchor.config import load_profile                    # noqa: E402
from anchor.unique import COVER_MIN_DISTANCE, cover_distance  # noqa: E402
from anchor.video import frame_169                        # noqa: E402

SITE = ROOT / "site"


def fix(drop_id: str, tries: int = 48) -> dict:
    profile = load_profile()
    cat = json.loads((SITE / "data" / "catalog.json").read_text())
    d = next(x for x in cat["drops"] if x["id"] == drop_id)
    others = [p for p in (SITE / "thumbs").glob("*.jpg") if p.stem != drop_id]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mp3 = tmp / "song.mp3"
        urllib.request.urlretrieve(d["audio_url"], mp3)
        audio = decode(mp3)
        feat = soundart.features(audio, SR, float(d["bpm"]))
        gs = tuple(genremod.for_lane(profile, d["lane"]))
        minor = "minor" in str(d.get("key", "")).lower()
        brief = {"title": d["title"], "bpm": d["bpm"], "seed": 0, "art_seed": 0}
        best = None
        for variant in range(1, tries):
            raw = tmp / "cover_art_raw.jpg"
            soundart.render(feat, gs, minor, variant=variant).save(raw, quality=95)
            brief["art_seed"] = variant
            full = tmp / "frame.jpg"
            frame_169(raw, brief, genre_phrase(profile.lane(d["lane"])), profile.artist["name"], full,
                      d.get("accent") or "#ff3bd4")
            small = tmp / "small.jpg"
            Image.open(full).convert("RGB").resize((480, 270), Image.LANCZOS).save(small, quality=85)
            dist, twin = min((cover_distance(small, o), o.stem) for o in others)
            print(f"variant {variant}: {dist:.1f} to {twin}")
            if best is None or dist > best[0]:
                best = (dist, twin, variant)
            if dist >= COVER_MIN_DISTANCE + 4:      # a margin over the limit, so it stays clear
                (SITE / "thumbs" / "full").mkdir(parents=True, exist_ok=True)
                Image.open(full).convert("RGB").resize((1280, 720), Image.LANCZOS).save(
                    SITE / "thumbs" / "full" / f"{drop_id}.jpg", quality=90)
                Image.open(small).save(SITE / "thumbs" / f"{drop_id}.jpg", quality=85)
                break
        else:
            raise SystemExit(f"no clear thumbnail in {tries} redraws (best {best})")
    video = d["youtube_url"].rsplit("/", 1)[-1]
    up_path = SITE / "data" / "uploads.json"
    up = json.loads(up_path.read_text())
    fixes = up.setdefault("thumb_fixes", [])
    if not any(f["video"] == video for f in fixes):
        fixes.append({"drop": drop_id, "video": video, "image": f"site/thumbs/full/{drop_id}.jpg"})
    up_path.write_text(json.dumps(up, indent=2, ensure_ascii=False) + "\n")
    out = {"drop": drop_id, "video": video, "distance": dist, "nearest": twin, "variant": variant}
    print(json.dumps(out))
    return out


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        fix(arg)
