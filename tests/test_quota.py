"""As many songs a day as the YouTube quota allows (Anchit, 2026-10-24: "max possible")."""
import json
from datetime import datetime, timezone
from pathlib import Path

from anchor import quota
from anchor.config import load_profile

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 25, 20, 0, tzinfo=timezone.utc)          # 13:00 Pacific (PDT)


def drop(i, when, short_via="buffer", failed=False, status="public"):
    return {"id": i, "date": i[:10], "status": status, "youtube_via": "youtube_api", "short_via": short_via,
            "short_buffer_failed": failed, "created_at": when}


def test_the_quota_day_is_the_pacific_day():
    assert quota.day_start(NOW) == datetime(2026, 10, 25, 7, 0, tzinfo=timezone.utc)
    winter = datetime(2026, 12, 1, 6, 0, tzinfo=timezone.utc)                     # 22:00 PST the day before
    assert quota.day_start(winter) == datetime(2026, 11, 30, 8, 0, tzinfo=timezone.utc)


def test_costs():
    assert quota.cost(drop("2026-10-25", "x")) == 1700
    assert quota.cost(drop("2026-10-25", "x", short_via="youtube_api")) == 3300
    assert quota.cost({"youtube_via": "buffer"}) == 0


def test_spend_counts_only_todays_quota_day():
    drops = [drop("2026-10-24-3", "2026-10-25T06:30:00Z"),    # before the 07:00 UTC reset: yesterday's quota
             drop("2026-10-25", "2026-10-25T10:10:00Z"),
             drop("2026-10-25-2", "2026-10-25T13:10:00Z", short_via="youtube_api")]
    assert quota.used(drops, NOW) == 1700 + 3300


def test_five_songs_a_day_while_shorts_go_through_buffer():
    drops, made = [], []
    for n, hour in enumerate((10, 13, 16, 19, 22, 23), start=1):
        now = datetime(2026, 10, 25, hour, 5, tzinfo=timezone.utc)
        nxt, why = quota.next_drop(drops, "2026-10-25", 5, 9500, now)
        if nxt is None:
            break
        made.append(nxt)
        drops.append(drop(nxt, now.isoformat().replace("+00:00", "Z")))
    assert made == ["2026-10-25", "2026-10-25-2", "2026-10-25-3", "2026-10-25-4", "2026-10-25-5"]
    assert "all 5 songs" in why


def test_two_a_day_when_buffer_fails():
    drops, made = [], []
    for hour in (10, 13, 16, 19):
        now = datetime(2026, 10, 25, hour, 5, tzinfo=timezone.utc)
        nxt, why = quota.next_drop(drops, "2026-10-25", 5, 9500, now)
        if nxt is None:
            break
        made.append(nxt)
        drops.append(drop(nxt, now.isoformat().replace("+00:00", "Z"), short_via="youtube_api", failed=True))
    assert made == ["2026-10-25", "2026-10-25-2"]
    assert "quota" in why and "midnight Pacific" in why


def test_failed_or_dry_run_slots_are_made_again_and_the_order_never_skips():
    drops = [drop("2026-10-25", "2026-10-25T10:10:00Z", status="error")]
    assert quota.next_drop(drops, "2026-10-25", 5, 9500, NOW)[0] == "2026-10-25"
    drops = [drop("2026-10-25", "2026-10-25T10:10:00Z"), drop("2026-10-25-3", "2026-10-25T13:10:00Z")]
    assert quota.next_drop(drops, "2026-10-25", 5, 9500, NOW)[0] == "2026-10-25-2"


def test_the_profile_allows_five_with_headroom():
    p = load_profile()
    assert p.schedule["max_drops_per_day"] == 5 and len(p.schedule["extra_post_times_utc"]) == 4
    assert p.youtube["daily_quota_budget"] <= 10_000 - 300, "headroom for the Uploads, sync and playlist jobs"
    assert p.youtube["shorts_via"] == "buffer"
    assert 5 * quota.COST_BUFFER_SHORT <= p.youtube["daily_quota_budget"] < 3 * quota.COST_API_SHORT


def test_the_cli_prints_the_next_drop(tmp_path, monkeypatch):
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps({"drops": []}))
    monkeypatch.setattr("anchor.__main__.CATALOG_PATH", cat, raising=False)
    from anchor.__main__ import main
    import io, contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(["next-drop", "--date", "2026-10-25"])
    assert out.getvalue().strip() == "2026-10-25"


# ------------------------------------------------- the Short through Buffer, full track via API
class FakeBuffer:
    def __init__(self, fail=False):
        self.fail, self.shorts = fail, []

    def youtube_channel(self, *a):
        return {"id": "buf-yt", "name": "ANCHOR"}

    def create_short(self, channel_id, **kw):
        from anchor.publish import BufferError
        if self.fail:
            raise BufferError("createPost rejected: channel disconnected")
        self.shorts.append(kw)
        return {"id": "bufpost1", "status": "sending", "dueAt": None, "externalLink": None}


def _publish(monkeypatch, tmp_path, buf):
    from test_mix_youtube import FakeGoogle
    from anchor import pipeline, youtube
    from anchor.brief import make_brief
    g = FakeGoogle()
    monkeypatch.setattr(youtube, "_http", g)
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("BUFFER_API_KEY", "k")
    monkeypatch.setattr(pipeline, "Buffer", lambda key: buf)
    monkeypatch.setattr(pipeline, "verify_media_url", lambda url, **kw: {"url": url, "bytes": 10})
    p = load_profile()
    b = make_brief(p, "2026-10-25-3", [])
    for name in ("a-full-169.mp4", "a-short.mp4", "frame-169.jpg"):
        (tmp_path / name).write_bytes(b"\x00" * 10)
    meta = {"brief": b, "full": {"full_169": {"size_bytes": 10}, "full_916": {"size_bytes": 10}}, "video": {"size_bytes": 10},
            "files": {"full_169": "a-full-169.mp4", "short": "a-short.mp4", "thumbnail": "frame-169.jpg"}}
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    res = pipeline.publish(p, tmp_path, "https://host/a-full-169.mp4", short_url="https://host/a-short.mp4")
    uploads = [c for c in g.calls if c[0] == "POST" and c[1].endswith("/videos")]
    return res, uploads


def test_the_short_goes_through_buffer_and_only_the_full_track_spends_quota(monkeypatch, tmp_path):
    buf = FakeBuffer()
    res, uploads = _publish(monkeypatch, tmp_path, buf)
    assert len(uploads) == 1 and res["youtube"]["via"] == "youtube_api" and res["youtube"]["post_id"] == "vid1"
    assert res["youtube_short"]["via"] == "buffer" and res["youtube_short"]["post_id"] == "bufpost1"
    sent = buf.shorts[0]
    assert sent["video_url"] == "https://host/a-short.mp4" and sent["notify"] is False
    assert "https://youtu.be/vid1" in sent["description"], "the Short links its full track"
    assert res["error"] is None and "short_buffer_error" not in res


def test_a_buffer_failure_falls_back_to_the_api_and_is_remembered(monkeypatch, tmp_path):
    res, uploads = _publish(monkeypatch, tmp_path, FakeBuffer(fail=True))
    assert len(uploads) == 2 and res["youtube_short"]["via"] == "youtube_api"
    assert "disconnected" in res["short_buffer_error"] and res["error"] is None
    from anchor import pipeline
    src = (ROOT / "anchor" / "pipeline.py").read_text()
    assert '"short_buffer_failed": bool(pub.get("short_buffer_error"))' in src
    assert quota.next_cost([{"youtube_via": "youtube_api", "short_via": "youtube_api", "short_buffer_failed": True,
                             "created_at": "2026-10-25T10:00:00Z"}]) == quota.COST_API_SHORT


# ------------------------------------------- one run plans the whole day (renders side by side)
def test_the_plan_is_every_missing_song_the_quota_allows():
    assert quota.plan([], "2026-10-25", 5, 9500, NOW)[0] == ["2026-10-25", "2026-10-25-2", "2026-10-25-3",
                                                             "2026-10-25-4", "2026-10-25-5"]
    done = [drop("2026-10-25", "2026-10-25T10:10:00Z"), drop("2026-10-25-3", "2026-10-25T13:10:00Z")]
    ids, why = quota.plan(done, "2026-10-25", 5, 9500, NOW)
    assert ids == ["2026-10-25-2", "2026-10-25-4", "2026-10-25-5"] and "3400" in why
    failed = [drop("2026-10-25", "2026-10-25T10:10:00Z", short_via="youtube_api", failed=True)]
    assert quota.plan(failed, "2026-10-25", 5, 9500, NOW)[0] == ["2026-10-25-2"], "3,300 a song after a Buffer failure"
    full = [drop(i, "2026-10-25T10:10:00Z") for i in ("2026-10-25", "2026-10-25-2", "2026-10-25-3", "2026-10-25-4", "2026-10-25-5")]
    assert quota.plan(full, "2026-10-25", 5, 9500, NOW) == ([], "all 5 songs for 2026-10-25 are out")
    api = [drop(f"2026-10-24-{n}", "2026-10-25T10:10:00Z", short_via="youtube_api") for n in (2, 3)]
    ids, why = quota.plan(api, "2026-10-25", 5, 6000, NOW)
    assert ids == [] and "midnight Pacific" in why


def test_one_more_song_fits_until_the_budget_is_spent():
    spent = [drop(f"2026-10-25-{n}", "2026-10-25T10:10:00Z") for n in (2, 3, 4, 5)]
    assert quota.room_for_one(spent, 9500, NOW)[0] is True          # 6,800 + 1,700
    assert quota.room_for_one(spent + [drop("2026-10-25", "2026-10-25T11:00:00Z")], 9500, NOW)[0] is False


def test_reserve_holds_the_earlier_songs_so_parallel_songs_differ(tmp_path, monkeypatch):
    """The 3rd song of a plan, rendered on its own runner, sees songs 1 and 2 as history."""
    from anchor.brief import make_brief
    from anchor.__main__ import main
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps({"drops": []}))
    monkeypatch.setattr("anchor.__main__.CATALOG_PATH", cat, raising=False)
    plan = ["2026-10-25", "2026-10-25-2", "2026-10-25-3"]
    main(["reserve", "--plan", json.dumps(plan), "--drop", "2026-10-25-3"])
    held = json.loads(cat.read_text())["drops"]
    assert [d["id"] for d in held] == ["2026-10-25-2", "2026-10-25"] and {d["status"] for d in held} == {"planned"}
    p = load_profile()
    # exactly the briefs the other runners make for themselves
    first = make_brief(p, "2026-10-25", [])
    second = make_brief(p, "2026-10-25-2", [{k: first[k] for k in ("id", "date", "title", "lane", "family", "key", "theme")}])
    assert held[1]["title"] == first["title"] and held[0]["title"] == second["title"]
    from anchor import catalog
    third = make_brief(p, "2026-10-25-3", catalog.history(json.loads(cat.read_text())))
    assert third["lane"] != second["lane"] and third["title"] not in (first["title"], second["title"])
    assert len({first["theme"], second["theme"], third["theme"]}) == 3, "songs rendered side by side have their own themes"
    main(["reserve", "--plan", json.dumps(plan), "--drop", "2026-10-25"])     # the first song holds nothing new
    assert len(json.loads(cat.read_text())["drops"]) == 2
    # planned songs never count as made or as spent quota
    assert quota.plan(held, "2026-10-25", 5, 9500, NOW)[0][:2] == ["2026-10-25", "2026-10-25-2"]


def test_the_cli_plans_the_day(tmp_path, monkeypatch, capsys):
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps({"drops": []}))
    monkeypatch.setattr("anchor.__main__.CATALOG_PATH", cat, raising=False)
    from anchor.__main__ import main
    main(["plan-drops", "--date", "2026-10-25"])
    assert json.loads(capsys.readouterr().out) == ["2026-10-25", "2026-10-25-2", "2026-10-25-3", "2026-10-25-4", "2026-10-25-5"]
    main(["quota-ok"])
    assert capsys.readouterr().out.strip() == "yes"


def test_only_the_queued_song_carries_its_stamp_back(tmp_path, monkeypatch):
    """Every runner ships queue.json; only the song that came from the queue may stamp it, and
    a song queued from the site during the render is kept."""
    from anchor import queue as qmod
    from anchor.__main__ import main
    qdir = tmp_path / "queue"
    qdir.mkdir()
    monkeypatch.setattr(qmod, "QUEUE", qdir)
    (qdir / "queue.json").write_text(json.dumps({"a.m4a": {"title": "A"}, "new.m4a": {"title": "New"}}))
    b = tmp_path / "build"
    for d, eng, q in (("2026-10-25", "queue", {"a.m4a": {"title": "A", "released_at": "2026-10-25T12:00:00Z"}}),
                      ("2026-10-25-2", "acestep", {"a.m4a": {"title": "A"}})):
        (b / d).mkdir(parents=True)
        (b / d / "meta.json").write_text(json.dumps({"engine": {"engine": eng}}))
        (b / d / "queue.json").write_text(json.dumps(q))
    main(["queue-stamp", "--build", str(b), "--drops", "2026-10-25", "2026-10-25-2"])
    q = json.loads((qdir / "queue.json").read_text())
    assert q["a.m4a"]["released_at"] == "2026-10-25T12:00:00Z" and q["new.m4a"] == {"title": "New"}
    (qdir / "queue.json").write_text(json.dumps({"a.m4a": {"title": "A"}}))
    main(["queue-stamp", "--build", str(b), "--drops", "2026-10-25-2"])     # the queued song was not posted
    assert "released_at" not in json.loads((qdir / "queue.json").read_text())["a.m4a"]


def test_a_song_goes_live_the_moment_it_is_uploaded(monkeypatch, tmp_path):
    """Anchit, 2026-10-26: live as soon as ready, not at the 23:00 IST slot."""
    from anchor.config import load_profile as lp
    p = lp()
    assert p.schedule["go_live"] == "when_ready"
    buf = FakeBuffer()
    from test_mix_youtube import FakeGoogle
    from anchor import pipeline, youtube
    from anchor.brief import make_brief

    def run(mode):
        g = FakeGoogle()
        monkeypatch.setattr(youtube, "_http", g)
        for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
            monkeypatch.setenv(k, "x")
        monkeypatch.setenv("BUFFER_API_KEY", "k")
        monkeypatch.setattr(pipeline, "Buffer", lambda key: buf)
        monkeypatch.setattr(pipeline, "verify_media_url", lambda url, **kw: {"url": url, "bytes": 10})
        prof = lp()
        prof.schedule["go_live"] = mode
        d = tmp_path / mode
        d.mkdir()
        b = make_brief(prof, "2030-01-01-3", [])           # a slot far in the future
        for name in ("a-full-169.mp4", "a-short.mp4", "frame-169.jpg"):
            (d / name).write_bytes(b"\x00" * 10)
        (d / "meta.json").write_text(json.dumps({"brief": b, "full": {}, "video": {"size_bytes": 10},
                                                 "files": {"full_169": "a-full-169.mp4", "short": "a-short.mp4",
                                                           "thumbnail": "frame-169.jpg"}}))
        res = pipeline.publish(prof, d, "https://host/a-full-169.mp4", short_url="https://host/a-short.mp4")
        meta = [json.loads(c[3]) for c in g.calls if c[0] == "POST" and "/upload/youtube/v3/videos" in c[1]]
        return res, meta[0]["status"], buf.shorts[-1]

    res, status, short = run("when_ready")
    assert "publishAt" not in status and status["privacyStatus"] == "public" and res["youtube"]["status"] == "public"
    assert not short.get("due_at"), "the Short goes out now too"
    res, status, short = run("scheduled")
    assert status["privacyStatus"] == "private" and status["publishAt"].startswith("2030-01-01")
