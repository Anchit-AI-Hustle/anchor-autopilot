"""CLI: python -m anchor <plan|make|publish|record|sync|fail|check> ..."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import catalog, pipeline
from .brief import make_brief
from .config import CATALOG_PATH, STATUS_PATH, env, load_profile
from .util import read_json


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="anchor", description="ANCHOR daily drop robot")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="print today's brief")
    p.add_argument("--date", default=None)

    m = sub.add_parser("make", help="generate track, master, cover and Short")
    m.add_argument("--date", default=None)
    m.add_argument("--out", default=None)
    m.add_argument("--engine", default=None, choices=["acestep_cpp", "fixture"])
    m.add_argument("--art", default=None, choices=["auto", "cloudflare", "procedural"])
    m.add_argument("--retries", type=int, default=1)

    pb = sub.add_parser("publish", help="send the Short to YouTube via Buffer")
    pb.add_argument("--drop", required=True)
    pb.add_argument("--media-url", required=True)
    pb.add_argument("--dry-run", action="store_true")
    pb.add_argument("--now", action="store_true", help="publish immediately instead of at post_time_utc")
    pb.add_argument("--site-only", action="store_true", help="release on the website only (no Buffer key)")

    r = sub.add_parser("record", help="add the drop to the website catalog")
    r.add_argument("--drop", required=True)
    r.add_argument("--repo", default=env("GITHUB_REPOSITORY"))
    r.add_argument("--short-url", default=None)
    r.add_argument("--run-url", default=None)

    s = sub.add_parser("sync", help="refresh Buffer status / YouTube links for recent drops")
    s.add_argument("--limit", type=int, default=7)

    f = sub.add_parser("fail", help="mark the last run as failed on the status page")
    f.add_argument("--stage", required=True)
    f.add_argument("--error", required=True)
    f.add_argument("--run-url", default=None)

    ss = sub.add_parser("suno-sync", help="read a public Suno profile, rate every song, publish it to the site")
    ss.add_argument("--handle", default=None)

    sub.add_parser("check", help="validate profile and site data")

    h = sub.add_parser("has-drop", help="print yes/no: is there already a published drop for the date")
    h.add_argument("--date", default=None)

    args = ap.parse_args(argv)
    profile = load_profile()

    if args.cmd == "plan":
        day = args.date or pipeline.today_utc()
        brief = make_brief(profile, day, catalog.history(catalog.load(CATALOG_PATH)))
        print(json.dumps(brief, indent=2, ensure_ascii=False))
    elif args.cmd == "make":
        day = args.date or pipeline.today_utc()
        out = Path(args.out or f"build/{day}")
        meta = pipeline.make(profile, day, out, engine_name=args.engine, art_mode=args.art, retries=args.retries)
        print(json.dumps({"out": str(out), "title": meta["brief"]["title"], "files": meta["files"]}))
    elif args.cmd == "publish":
        res = pipeline.publish(profile, Path(args.drop), args.media_url, dry_run=args.dry_run, now=args.now,
                               site_only=args.site_only)
        print(json.dumps(res, indent=2))
    elif args.cmd == "record":
        drop = pipeline.record(profile, Path(args.drop), repo=args.repo, short_url=args.short_url,
                               run_url=args.run_url)
        print(json.dumps(drop, indent=2))
    elif args.cmd == "sync":
        pipeline.sync(profile, limit=args.limit)
    elif args.cmd == "suno-sync":
        from .suno import catalogue
        cat = catalog.load(CATALOG_PATH, profile)
        cat["catalogue"] = catalogue(args.handle or profile.artist.get("suno_handle", "anchor_at"))
        catalog.save(cat, CATALOG_PATH)
        c = cat["catalogue"]
        print(json.dumps({"total": c["total"], "postable": c["postable"], "checked_at": c["checked_at"]}))
    elif args.cmd == "fail":
        pipeline.fail(args.stage, args.error, args.run_url)
    elif args.cmd == "check":
        return check(profile)
    elif args.cmd == "has-drop":
        day = args.date or pipeline.today_utc()
        drops = catalog.load(CATALOG_PATH).get("drops", [])
        done = any(d.get("id") == day and d.get("status") not in ("dry-run", "error") for d in drops)
        print("yes" if done else "no")
    return 0


def check(profile) -> int:
    """Validate the catalog/status files the website depends on."""
    problems = []
    cat = read_json(CATALOG_PATH, {"drops": []}) or {"drops": []}
    ids = [d.get("id") for d in cat.get("drops", [])]
    if len(ids) != len(set(ids)):
        problems.append("duplicate drop ids in catalog")
    if ids != sorted(ids, reverse=True):
        problems.append("catalog drops are not sorted newest first")
    for d in cat.get("drops", []):
        for key in ("id", "title", "bpm", "key", "cover", "status"):
            if d.get(key) in (None, ""):
                problems.append(f"drop {d.get('id')}: missing {key}")
        cover = CATALOG_PATH.parent.parent / (d.get("cover") or "")
        if d.get("cover") and not cover.exists():
            problems.append(f"drop {d.get('id')}: cover file {d['cover']} missing")
    status = read_json(STATUS_PATH, {}) or {}
    if status and "last_run" in status and status["last_run"].get("result") not in ("ok", "failed", "dry-run", "pending"):
        problems.append("status.last_run.result invalid")
    for msg in problems:
        print("CHECK FAIL:", msg, file=sys.stderr)
    print(f"check: profile ok ({len(profile.lanes)} lanes, {len(profile.families)} families), "
          f"catalog {len(ids)} drop(s), {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
