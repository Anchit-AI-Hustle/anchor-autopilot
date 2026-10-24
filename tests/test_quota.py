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
