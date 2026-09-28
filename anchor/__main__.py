"""CLI: python -m anchor <plan|make|publish|record|sync|suno-sync|queue-add|fail|check> ..."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import catalog, ledger, pipeline, queue
from .brief import make_brief
from .config import CATALOG_PATH, LEDGER_PATH, STATUS_PATH, env, load_profile
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
    m.add_argument("--no-queue", action="store_true",
                   help="generate even if tracks are queued (test the model without spending one)")

    pb = sub.add_parser("publish", help="send the full track and the Short to YouTube and the Reel to Instagram via Buffer")
    pb.add_argument("--drop", required=True)
    pb.add_argument("--media-url", required=True)
    pb.add_argument("--dry-run", action="store_true")
    pb.add_argument("--now", action="store_true", help="publish immediately instead of at post_time_utc")
    pb.add_argument("--site-only", action="store_true", help="release on the website only (no Buffer key)")
    pb.add_argument("--reel-url", default=None, help="public https URL of the 9:16 file for Instagram")
    pb.add_argument("--short-url", default=None, help="public https URL of the 45 s cut for the YouTube Short")
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

    qa = sub.add_parser("queue-add", help="pull a Suno song into the release queue (the site's Add to YouTube button)")
    qa.add_argument("--song", required=True, help="Suno song id, song URL, or text containing one")
    qa.add_argument("--handle", default=None)
    qa.add_argument("--force", action="store_true", help="release it even if it is another take of a song already out (the audio gate still runs)")
    qp = sub.add_parser("queue-plan", help="every public Suno song: released, queued, eligible or held, and why")
    qp.add_argument("--handle", default=None)
    qp.add_argument("--offline", action="store_true", help="use the synced catalogue instead of reading Suno")

    mx = sub.add_parser("mix", help="build the week's or month's mix: audio, cover, 16:9 video, chapters")
    mx.add_argument("--period", default="week", choices=["week", "month"])
    mx.add_argument("--date", default=None, help="last day of the period (default: today in UTC)")
    mx.add_argument("--out", default=None)
    mx.add_argument("--art", default=None, choices=["auto", "cloudflare", "procedural"])
    pm = sub.add_parser("publish-mix", help="send the mix video to YouTube (own credentials, or Buffer)")
    pm.add_argument("--mix", required=True)
    pm.add_argument("--media-url", default=None, help="public https URL of the mix video, for the Buffer road")
    pm.add_argument("--dry-run", action="store_true")
    pm.add_argument("--now", action="store_true")
    rm = sub.add_parser("record-mix", help="add the mix to the website catalog and the ledger")
    rm.add_argument("--mix", required=True)
    rm.add_argument("--repo", default=env("GITHUB_REPOSITORY"))
    ya = sub.add_parser("youtube-auth", help="one-time, on your own machine: get the channel's refresh token for YT_REFRESH_TOKEN")
    ya.add_argument("--client-id", required=True)
    ya.add_argument("--client-secret", required=True)
    ya.add_argument("--port", type=int, default=8765)

    rt = sub.add_parser("retitle", help="give every upload on the channel the search-led title and description (Data API)")
    rt.add_argument("--dry-run", action="store_true")

    vs = sub.add_parser("versions", help="one version of each record everywhere: build, then publish (site/data/versions.json)")
    vs.add_argument("stage", choices=["build", "publish"])
    vs.add_argument("--only", default=None, help="one record id (YYYY-MM-DD)")
    vs.add_argument("--out", default="build/versions")
    vs.add_argument("--repo", default=env("GITHUB_REPOSITORY") or "Anchit-AI-Hustle/anchor-autopilot")

    fv = sub.add_parser("fullvideos", help="every Short on the channel gets its full track as a video (Data API)")
    fv.add_argument("--max", type=int, default=2, help="uploads this run (1,600 API units each; the channel has 10,000 a day)")
    fv.add_argument("--dry-run", action="store_true", help="list what would be linked or uploaded, change nothing")
    fv.add_argument("--out", default="build/fullvideos")
    fv.add_argument("--repo", default=env("GITHUB_REPOSITORY") or "Anchit-AI-Hustle/anchor-autopilot")
    sub.add_parser("check", help="validate profile and site data")
    sub.add_parser("ledger", help="refresh the /ops ledger's upload rows from the catalog")

    h = sub.add_parser("has-drop", help="print yes/no: is there already a published drop for the date")
    h.add_argument("--date", default=None)
    cd = sub.add_parser("cadence", help="print yes/no: is the date a release day on the every-N-days schedule")
    cd.add_argument("--date", default=None)

    args = ap.parse_args(argv)
    profile = load_profile()

    if args.cmd == "plan":
        day = args.date or pipeline.today_utc()
        brief = make_brief(profile, day, catalog.history(catalog.load(CATALOG_PATH)))
        print(json.dumps(brief, indent=2, ensure_ascii=False))
    elif args.cmd == "make":
        day = args.date or pipeline.today_utc()
        out = Path(args.out or f"build/{day}")
        meta = pipeline.make(profile, day, out, engine_name=args.engine, art_mode=args.art,
                             retries=args.retries, use_queue=not args.no_queue)
        print(json.dumps({"out": str(out), "title": meta["brief"]["title"], "files": meta["files"]}))
    elif args.cmd == "publish":
        res = pipeline.publish(profile, Path(args.drop), args.media_url, dry_run=args.dry_run, now=args.now,
                               site_only=args.site_only, reel_url=args.reel_url, short_url=args.short_url)
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
        # what the robot will do with each song, written where the site can show it
        from . import autoqueue
        plan = {r["id"]: {"verdict": r["verdict"], "reason": r["reason"]} for r in autoqueue.plan(profile, cat["catalogue"]["songs"])}
        for song in cat["catalogue"]["songs"]:
            song["decision"] = plan.get(song["id"])
        catalog.save(cat, CATALOG_PATH)
        c = cat["catalogue"]
        print(json.dumps({"total": c["total"], "postable": c["postable"], "checked_at": c["checked_at"]}))
    elif args.cmd == "queue-add":
        from . import suno
        handle = args.handle or profile.artist.get("suno_handle", "anchor_at")
        song = suno.find(handle, args.song)
        if not song["postable"]:
            print(f"note: {song['title']!r} is rated {song['rating']} and marked not-postable "
                  f"({song['verdict']}) - queueing anyway because you asked for it", file=sys.stderr)
        res = suno.queue_entry(song, queue.QUEUE, force=args.force)
        print(json.dumps({"queued": res["name"], "title": song["title"], "rating": song["rating"],
                          "suno_url": song["url"],
                          "waiting": len(queue.pending()) + len(queue.reserved())},
                         ensure_ascii=False))
    elif args.cmd == "mix":
        from . import mix
        day = args.date or pipeline.today_utc()
        out = Path(args.out or f"build/mix-{args.period}-{day}")
        meta = mix.build(profile, catalog.load(CATALOG_PATH, profile), day, args.period, out, art_mode=args.art)
        print(json.dumps({"out": str(out), "title": meta["title"], "tracks": len(meta["chapters"]),
                          "duration_s": meta["duration_s"], "files": meta["files"]}))
    elif args.cmd == "publish-mix":
        res = pipeline.publish_mix(profile, Path(args.mix), args.media_url, dry_run=args.dry_run, now=args.now)
        print(json.dumps(res, indent=2))
    elif args.cmd == "record-mix":
        row = pipeline.record_mix(profile, Path(args.mix), repo=args.repo)
        print(json.dumps(row, indent=2))
    elif args.cmd == "retitle":
        from . import retitle
        print(json.dumps(retitle.run(profile, dry_run=args.dry_run), indent=2, ensure_ascii=False))
    elif args.cmd == "versions":
        from . import versions
        data, cat = versions.load(), catalog.load(CATALOG_PATH, profile)
        drops = {d["id"]: d for d in cat["drops"]}
        stage = "built" if args.stage == "build" else "published"
        todo = [e for e in versions.pending(data, stage) if (not args.only or e["id"] == args.only)
                and (stage == "built" or "built" in e)]         # a record goes up only once it is built
        done = []
        for e in todo:
            work = Path(args.out) / e["id"]
            try:
                _version_step(args, profile, versions, e, drops, cat, work)
            finally:                                          # a half-published entry keeps what landed
                versions.save(data)
                catalog.save(cat, CATALOG_PATH)
            done.append(e["id"])
        print(json.dumps({"stage": args.stage, "done": done}))
    elif args.cmd == "fullvideos":
        from . import fullvideos
        out = fullvideos.run(profile, repo=args.repo, work=Path(args.out), limit=args.max, dry_run=args.dry_run)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 1 if out["errors"] else 0
    elif args.cmd == "youtube-auth":
        from .youtube import authorize_interactively
        token = authorize_interactively(args.client_id, args.client_secret, args.port)
        print("\nYT_REFRESH_TOKEN (add it to the repository secrets, then close this window):\n\n" + token + "\n")
    elif args.cmd == "queue-plan":
        from . import autoqueue, suno
        if args.offline:
            songs = ((catalog.load(CATALOG_PATH).get("catalogue") or {}).get("songs")) or []
        else:
            songs = suno.catalogue(args.handle or profile.artist.get("suno_handle", "anchor_at"))["songs"]
        for r in autoqueue.plan(profile, songs):
            print(f"{r['verdict']:9} {str(r['title'])[:30]:30} {r.get('duration_s') or 0:5.0f}s r{r.get('rating')}  {r['reason']}")
    elif args.cmd == "fail":
        pipeline.fail(args.stage, args.error, args.run_url)
    elif args.cmd == "check":
        return check(profile)
    elif args.cmd == "ledger":
        book = ledger.load(LEDGER_PATH)
        n = ledger.refresh(book, catalog.load(CATALOG_PATH))
        ledger.save(book, LEDGER_PATH)
        print(f"ledger: {len(book['entries'])} entries, {n} upload row(s) refreshed")
    elif args.cmd == "cadence":
        day = args.date or pipeline.today_utc()
        print("yes" if pipeline.is_release_day(profile, day) else "no")
    elif args.cmd == "has-drop":
        day = args.date or pipeline.today_utc()
        drops = catalog.load(CATALOG_PATH).get("drops", [])
        done = any(d.get("id") == day and d.get("status") not in ("dry-run", "error") for d in drops)
        print("yes" if done else "no")
    return 0


def _version_step(args, profile, versions, e: dict, drops: dict, cat: dict, work: Path) -> None:
    """One record through one stage of ``anchor versions``."""
    if args.stage == "build":
        versions.record(cat, e, versions.build(profile, e, drops[e["id"]], args.repo, work), None)
        return
    from .retitle import CHANNEL_PATH
    if not (work / "meta.json").exists():             # built in an earlier run: the kept originals give the same files
        versions.build(profile, e, drops[e["id"]], args.repo, work)
    meta = json.loads((work / "meta.json").read_text())
    pub = versions.publish(profile, e, meta, work)
    versions.record(cat, e, meta, pub)
    channel = json.loads(CHANNEL_PATH.read_text())
    versions.remap_channel(channel, pub)
    CHANNEL_PATH.write_text(json.dumps(channel, indent=1, ensure_ascii=False))


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
    book = ledger.load(LEDGER_PATH)
    problems.extend(ledger.problems(book))
    for msg in problems:
        print("CHECK FAIL:", msg, file=sys.stderr)
    print(f"check: profile ok ({len(profile.lanes)} lanes, {len(profile.families)} families), "
          f"catalog {len(ids)} drop(s), ledger {len(book['entries'])} entr(ies), {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
