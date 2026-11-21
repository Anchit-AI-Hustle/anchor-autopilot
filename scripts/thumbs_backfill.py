"""One-off (2026-11-21): keep the thumbnail of every drop already released in site/thumbs, so the
uniqueness gate (anchor/pipeline.py thumb_distance) compares a new thumbnail with all of them.
Run from the repo root with gh logged in."""
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

out = Path("site/thumbs")
out.mkdir(parents=True, exist_ok=True)
tags = json.loads(subprocess.run(["gh", "release", "list", "--limit", "400", "--json", "tagName,isDraft"],
                                 capture_output=True, text=True, check=True).stdout)
kept = 0
for t in tags:
    tag = t["tagName"]
    if not tag.startswith("drop-") or t["isDraft"]:
        continue
    did = tag[len("drop-"):]
    if (out / f"{did}.jpg").exists():
        continue
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run(["gh", "release", "download", tag, "--pattern", "*frame-169.jpg", "--dir", tmp],
                           capture_output=True, text=True)
        files = sorted(Path(tmp).glob("*.jpg"))
        if r.returncode or not files:
            continue
        Image.open(files[0]).convert("RGB").resize((480, 270), Image.LANCZOS).save(out / f"{did}.jpg", quality=85)
        kept += 1
print(f"kept {kept} thumbnails; {len(list(out.glob('*.jpg')))} in site/thumbs")
