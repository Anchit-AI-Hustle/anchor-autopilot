import io
import json
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

from anchor import publish
from anchor.publish import Buffer, BufferError, build_post_input, schedule_for


class FakeResp(io.BytesIO):
    def __init__(self, payload, url="https://api.buffer.com", headers=None):
        super().__init__(json.dumps(payload).encode())
        self._url, self.headers = url, headers or {}

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_post_input_has_ai_disclosure_and_music_category():
    due = datetime(2026, 9, 11, 17, 30, tzinfo=timezone.utc)
    inp = build_post_input("ch1", title="Override Carbon", description="desc", video_url="https://x.io/a.mp4",
                           due_at=due)
    yt = inp["metadata"]["youtube"]
    assert yt["isAiGenerated"] is True and yt["categoryId"] == "10" and yt["privacy"] == "public"
    assert yt["madeForKids"] is False and yt["title"] == "Override Carbon"
    assert inp["mode"] == "customScheduled" and inp["dueAt"] == "2026-09-11T17:30:00Z"
    assert inp["assets"] == [{"video": {"url": "https://x.io/a.mp4"}}]
    now = build_post_input("ch1", title="t", description="d", video_url="https://x.io/a.mp4", due_at=None)
    assert now["mode"] == "shareNow" and "dueAt" not in now
    with pytest.raises(BufferError):
        build_post_input("ch1", title="t", description="d", video_url="http://x.io/a.mp4", due_at=None)


def test_schedule_for_publishes_now_when_slot_passed():
    slot = datetime(2026, 9, 11, 17, 30, tzinfo=timezone.utc)
    assert schedule_for(slot, now=slot - timedelta(hours=2)) == slot
    assert schedule_for(slot, now=slot - timedelta(minutes=5)) is None
    assert schedule_for(slot, now=slot + timedelta(minutes=5)) is None


def _router(responses, seen):
    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data.decode())
        seen.append(body)
        for key, payload in responses:
            if key in body["query"]:
                return FakeResp(payload)
        raise AssertionError("unexpected query " + body["query"])
    return fake_urlopen


def test_buffer_picks_anchor_channel_by_youtube_id(monkeypatch):
    seen = []
    monkeypatch.setattr(publish.urllib.request, "urlopen", _router([
        ("organizations", {"data": {"account": {"organizations": [{"id": "org1", "name": "A"}]}}}),
        ("channels", {"data": {"channels": [
            {"id": "c-ig", "name": "ig", "service": "instagram", "serviceId": "x", "isDisconnected": False,
             "isLocked": False, "isQueuePaused": False},
            {"id": "c-yt2", "name": "Other", "service": "youtube", "serviceId": "UCother", "isDisconnected": False,
             "isLocked": False, "isQueuePaused": False},
            {"id": "c-yt", "name": "ANCHOR", "service": "youtube", "serviceId": "UCAKPJrMOwspkOXY1aLKaAkQ",
             "isDisconnected": False, "isLocked": False, "isQueuePaused": False}]}}),
        ("createPost", {"data": {"createPost": {"post": {"id": "p1", "status": "buffer",
                                                         "dueAt": "2026-09-11T17:30:00Z", "externalLink": None}}}}),
    ], seen))
    buf = Buffer("key")
    ch = buf.youtube_channel("UCAKPJrMOwspkOXY1aLKaAkQ")
    assert ch["id"] == "c-yt"
    post = buf.create_short(ch["id"], title="T", description="D", video_url="https://x.io/v.mp4",
                            due_at=datetime(2026, 9, 11, 17, 30, tzinfo=timezone.utc))
    assert post["id"] == "p1"
    sent = seen[-1]["variables"]["input"]
    assert sent["channelId"] == "c-yt" and sent["metadata"]["youtube"]["isAiGenerated"] is True


def test_buffer_errors_are_explicit(monkeypatch):
    monkeypatch.setattr(publish.urllib.request, "urlopen", _router([
        ("organizations", {"data": {"account": {"organizations": [{"id": "org1", "name": "A"}]}}}),
        ("channels", {"data": {"channels": [
            {"id": "c-yt", "name": "ANCHOR", "service": "youtube", "serviceId": "UCAKPJrMOwspkOXY1aLKaAkQ",
             "isDisconnected": True, "isLocked": False, "isQueuePaused": False}]}}),
        ("createPost", {"data": {"createPost": {"message": "Failed to fetch video"}}}),
    ], []))
    buf = Buffer("key")
    with pytest.raises(BufferError, match="disconnected"):
        buf.youtube_channel("UCAKPJrMOwspkOXY1aLKaAkQ")
    with pytest.raises(BufferError, match="rejected"):
        buf.create_short("c-yt", title="T", description="D", video_url="https://x.io/v.mp4", due_at=None)
    with pytest.raises(BufferError, match="BUFFER_API_KEY"):
        Buffer("")


def test_buffer_retries_on_429(monkeypatch):
    calls = {"n": 0}

    def fake(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {"Retry-After": "0"},
                                         io.BytesIO(b'{"errors":[{"message":"slow down"}]}'))
        return FakeResp({"data": {"account": {"organizations": [{"id": "o", "name": "n"}]}}})

    monkeypatch.setattr(publish.urllib.request, "urlopen", fake)
    monkeypatch.setattr(publish.time, "sleep", lambda s: None)
    assert Buffer("k").organization_id() == "o"
    assert calls["n"] == 2


def test_verify_media_url_returns_direct_final_url(monkeypatch):
    def fake(req, timeout=None):
        return FakeResp({}, url="https://cdn.example.com/v.mp4",
                        headers={"Content-Type": "video/mp4", "Content-Range": "bytes 0-1023/5000000"})
    monkeypatch.setattr(publish.urllib.request, "urlopen", fake)
    res = publish.verify_media_url("https://host.example.com/v.mp4", expect_min_bytes=1000)
    assert res["url"] == "https://cdn.example.com/v.mp4" and res["bytes"] == 5_000_000


def test_verify_media_url_rejects_html(monkeypatch):
    def fake(req, timeout=None):
        return FakeResp({}, url="https://host.example.com/v.mp4", headers={"Content-Type": "text/html"})
    monkeypatch.setattr(publish.urllib.request, "urlopen", fake)
    monkeypatch.setattr(publish.time, "sleep", lambda s: None)
    with pytest.raises(BufferError, match="content-type"):
        publish.verify_media_url("https://host.example.com/v.mp4", attempts=2, wait_s=0)
