"""Publishing through Buffer's GraphQL API (free plan: 1 key, 250 requests/day).

Buffer posts to YouTube as a public Short and sets YouTube's "AI use" disclosure
(``isAiGenerated``). Media must be a public, direct, HTTPS URL - Buffer fetches
it when the post goes out.
"""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from .util import iso, log

API = "https://api.buffer.com"


class BufferError(RuntimeError):
    pass


class Buffer:
    def __init__(self, api_key: str, timeout: int = 60):
        if not api_key:
            raise BufferError("BUFFER_API_KEY is not set")
        self.api_key = api_key
        self.timeout = timeout

    def gql(self, query: str, variables: dict | None = None, attempts: int = 3) -> dict:
        body = json.dumps({"query": query, "variables": variables or {}}).encode()
        for attempt in range(1, attempts + 1):
            req = urllib.request.Request(API, data=body, method="POST", headers={
                "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                "User-Agent": "anchor-autopilot/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                text = exc.read().decode("utf-8", "replace")[:500]
                if exc.code == 429 and attempt < attempts:
                    wait = int(exc.headers.get("Retry-After", "30") or 30)
                    if wait > 900:
                        raise BufferError(f"rate limited for {wait}s: {text}") from exc
                    log(f"buffer: 429, waiting {wait}s")
                    time.sleep(wait + random.uniform(0, 3))
                    continue
                if exc.code >= 500 and attempt < attempts:
                    time.sleep(5 * attempt)
                    continue
                raise BufferError(f"HTTP {exc.code}: {text}") from exc
            except urllib.error.URLError as exc:
                if attempt < attempts:
                    time.sleep(5 * attempt)
                    continue
                raise BufferError(f"network error: {exc}") from exc
            if payload.get("errors"):
                raise BufferError("GraphQL error: " + "; ".join(e.get("message", "?") for e in payload["errors"]))
            return payload["data"]
        raise BufferError("unreachable")

    # ---------------------------------------------------------------- discovery
    def organization_id(self) -> str:
        data = self.gql("query { account { organizations { id name } } }")
        orgs = data["account"]["organizations"]
        if not orgs:
            raise BufferError("Buffer account has no organization")
        return orgs[0]["id"]

    def youtube_channel(self, youtube_channel_id: str | None = None, channel_id: str | None = None) -> dict:
        org = self.organization_id()
        data = self.gql(
            "query($org: OrganizationId!) { channels(input: {organizationId: $org}) "
            "{ id name displayName service serviceId isDisconnected isLocked isQueuePaused } }",
            {"org": org})
        channels = [c for c in data["channels"] if c.get("service") == "youtube"]
        if channel_id:
            channels = [c for c in channels if c["id"] == channel_id]
        elif youtube_channel_id and any(c.get("serviceId") == youtube_channel_id for c in channels):
            channels = [c for c in channels if c.get("serviceId") == youtube_channel_id]
        if not channels:
            raise BufferError("no YouTube channel connected in Buffer (connect @AT_ANCHOR in Buffer first)")
        if len(channels) > 1:
            raise BufferError("several YouTube channels in Buffer; set BUFFER_CHANNEL_ID")
        ch = channels[0]
        if ch.get("isDisconnected") or ch.get("isLocked"):
            raise BufferError(f"Buffer channel {ch.get('name')} is disconnected or locked; reconnect it in Buffer")
        if ch.get("isQueuePaused"):
            raise BufferError(f"Buffer queue for {ch.get('name')} is paused; resume it in Buffer")
        return ch

    # ------------------------------------------------------------------ posting
    def create_short(self, channel_id: str, *, title: str, description: str, video_url: str,
                     due_at: datetime | None, category_id: str = "10", privacy: str = "public",
                     ai_generated: bool = True, notify: bool = True) -> dict:
        variables = {"input": build_post_input(channel_id, title=title, description=description,
                                               video_url=video_url, due_at=due_at, category_id=category_id,
                                               privacy=privacy, ai_generated=ai_generated, notify=notify)}
        data = self.gql(
            "mutation($input: CreatePostInput!) { createPost(input: $input) { "
            "... on PostActionSuccess { post { id status dueAt externalLink } } "
            "... on MutationError { message } } }", variables)
        result = data["createPost"]
        if "post" not in result:
            raise BufferError(f"createPost rejected: {result.get('message', result)}")
        return result["post"]

    def post(self, post_id: str) -> dict:
        data = self.gql(
            "query($id: PostId!) { post(input: {id: $id}) { id status dueAt sentAt externalLink "
            "error { message supportUrl } } }", {"id": post_id})
        return data["post"]


def build_post_input(channel_id: str, *, title: str, description: str, video_url: str,
                     due_at: datetime | None, category_id: str = "10", privacy: str = "public",
                     ai_generated: bool = True, notify: bool = True) -> dict:
    if not video_url.startswith("https://"):
        raise BufferError("video URL must be https")
    inp = {
        "channelId": channel_id,
        "text": description[:4900],
        "schedulingType": "automatic",
        "mode": "customScheduled" if due_at else "shareNow",
        "assets": [{"video": {"url": video_url}}],
        "metadata": {"youtube": {
            "title": title[:100],
            "categoryId": category_id,
            "privacy": privacy,
            "madeForKids": False,
            "isAiGenerated": bool(ai_generated),
            "notifySubscribers": bool(notify),
            "embeddable": True,
        }},
    }
    if due_at:
        inp["dueAt"] = iso(due_at)
    return inp


def schedule_for(post_at: datetime, now: datetime | None = None, lead_minutes: int = 10) -> datetime | None:
    """Scheduled time for Buffer, or None to publish immediately if the slot already passed."""
    now = now or datetime.now(timezone.utc)
    return post_at if post_at - now >= timedelta(minutes=lead_minutes) else None


def verify_media_url(url: str, expect_min_bytes: int = 100_000, attempts: int = 12, wait_s: int = 15) -> dict:
    """Buffer needs a public, direct, HTTPS video URL. Wait until it serves, return the direct URL."""
    last = ""
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, method="GET", headers={"Range": "bytes=0-1023",
                                                                 "User-Agent": "anchor-autopilot/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                final = resp.geturl()
                ctype = resp.headers.get("Content-Type", "")
                crange = resp.headers.get("Content-Range", "")
                total = int(crange.rsplit("/", 1)[-1]) if "/" in crange else int(resp.headers.get("Content-Length", 0))
                if not final.startswith("https://"):
                    last = f"final URL is not https: {final}"
                elif "video" not in ctype and "octet-stream" not in ctype:
                    last = f"content-type {ctype!r}"
                elif total and total < expect_min_bytes:
                    last = f"only {total} bytes"
                else:
                    # Buffer wants a direct link: hand it the final URL if the host redirected
                    return {"url": final, "requested": url, "content_type": ctype, "bytes": total,
                            "attempts": attempt}
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
        except urllib.error.URLError as exc:
            last = f"network {exc.reason}"
        log(f"media URL not ready ({last}); retry {attempt}/{attempts}")
        time.sleep(wait_s)
    raise BufferError(f"media URL never became servable: {url} ({last})")
