"""Uploading straight to YouTube through the Data API v3, when the channel's own OAuth
credentials are in the environment (YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN).

What Buffer cannot do and this can: tags, the category, the AI disclosure flag, a scheduled
publish time, the custom thumbnail, the playlist, and the Short's exact link to its full
track (the full track is uploaded first, so its id is known). Buffer stays as the fallback
when the three variables are not set, and remains the road to Instagram.

Plain urllib, no SDK: a token refresh, a resumable upload in one request, two small POSTs.
Quota: an upload costs 1,600 of the daily 10,000 units; three uploads a day fit.

Getting the refresh token is a one-time step on your own machine, never in CI:
``python -m anchor youtube-auth`` prints a Google URL, you sign in as the channel, Google
sends the browser back to a loopback address, and the refresh token is printed for you to
put in the repository secrets.
"""
from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from .config import env
from .util import iso, log

TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
SCOPE = "https://www.googleapis.com/auth/youtube"
# Google retired the copy-the-code redirect in 2023; a desktop client now gets the code on a
# loopback address, so ``youtube-auth`` listens on one for a moment
REDIRECT = "http://127.0.0.1:{port}/"


class YouTubeError(RuntimeError):
    pass


def configured() -> bool:
    return all(env(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))


def _http(method: str, url: str, *, data: bytes | None = None, headers: dict | None = None, timeout: int = 120) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")[:600]
        raise YouTubeError(f"HTTP {exc.code} {method} {url.split('?')[0]}: {text}") from exc
    except urllib.error.URLError as exc:
        raise YouTubeError(f"network error: {exc}") from exc


def auth_url(client_id: str, port: int) -> str:
    q = {"client_id": client_id, "redirect_uri": REDIRECT.format(port=port), "response_type": "code", "scope": SCOPE,
         "access_type": "offline", "prompt": "consent"}
    return AUTH_URL + "?" + urllib.parse.urlencode(q)


def exchange_code(client_id: str, client_secret: str, code: str, port: int) -> dict:
    body = urllib.parse.urlencode({"code": code, "client_id": client_id, "client_secret": client_secret,
                                   "redirect_uri": REDIRECT.format(port=port), "grant_type": "authorization_code"}).encode()
    _, _, raw = _http("POST", TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    return json.loads(raw)


def authorize_interactively(client_id: str, client_secret: str, port: int = 8765) -> str:
    """Run once on your own machine. Opens nothing by itself: prints the URL, waits for
    Google to send the browser back to 127.0.0.1, exchanges the code, returns the refresh
    token. The token is printed for you and never logged anywhere else."""
    import http.server

    got: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):   # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got["code"] = (q.get("code") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ANCHOR: you can close this tab." if got["code"] else b"no code in the redirect")

        def log_message(self, *a):   # quiet
            pass

    print("Open this URL in the browser that is signed in as the channel:\n\n" + auth_url(client_id, port) + "\n")
    with http.server.HTTPServer(("127.0.0.1", port), Handler) as srv:
        while not got.get("code"):
            srv.handle_request()
    data = exchange_code(client_id, client_secret, got["code"], port)
    if "refresh_token" not in data:
        raise YouTubeError(f"no refresh token in the reply: {list(data)}")
    return data["refresh_token"]


class YouTube:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None, refresh_token: str | None = None):
        self.client_id = client_id or env("YT_CLIENT_ID") or ""
        self.client_secret = client_secret or env("YT_CLIENT_SECRET") or ""
        self.refresh_token = refresh_token or env("YT_REFRESH_TOKEN") or ""
        if not (self.client_id and self.client_secret and self.refresh_token):
            raise YouTubeError("YT_CLIENT_ID, YT_CLIENT_SECRET and YT_REFRESH_TOKEN are not all set")
        self._token: str | None = None

    # ------------------------------------------------------------------ auth
    def token(self) -> str:
        if self._token:
            return self._token
        body = urllib.parse.urlencode({"client_id": self.client_id, "client_secret": self.client_secret,
                                       "refresh_token": self.refresh_token, "grant_type": "refresh_token"}).encode()
        _, _, raw = _http("POST", TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        data = json.loads(raw)
        if "access_token" not in data:
            raise YouTubeError("token refresh returned no access_token")
        self._token = data["access_token"]
        return self._token

    def _headers(self, **extra) -> dict:
        return {"Authorization": f"Bearer {self.token()}", **extra}

    def _json(self, method: str, path: str, params: dict, body: dict | None = None) -> dict:
        url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
        data = json.dumps(body).encode() if body is not None else None
        _, _, raw = _http(method, url, data=data, headers=self._headers(**({"Content-Type": "application/json"} if body is not None else {})))
        return json.loads(raw) if raw else {}

    # ---------------------------------------------------------------- uploads
    def upload(self, video: Path, *, title: str, description: str, tags: list[str], category_id: str = "10",
               publish_at: datetime | None = None, privacy: str = "public", ai_generated: bool = True,
               language: str = "en", notify: bool = True) -> dict:
        """One resumable-upload session, sent in one request. Scheduled videos go up private
        with ``publishAt``; YouTube flips them public at that time."""
        snippet = {"title": title[:100], "description": description[:5000], "tags": tags[:60],
                   "categoryId": str(category_id), "defaultLanguage": language, "defaultAudioLanguage": "zxx"}
        status = {"selfDeclaredMadeForKids": False, "containsSyntheticMedia": bool(ai_generated),
                  "license": "youtube", "embeddable": True}
        if publish_at:
            status.update(privacyStatus="private", publishAt=iso(publish_at))
        else:
            status["privacyStatus"] = privacy
        meta = json.dumps({"snippet": snippet, "status": status}).encode()
        size = video.stat().st_size
        mime = mimetypes.guess_type(str(video))[0] or "video/mp4"
        params = {"uploadType": "resumable", "part": "snippet,status", "notifySubscribers": "true" if notify else "false"}
        _, headers, _ = _http("POST", f"{UPLOAD}/videos?{urllib.parse.urlencode(params)}", data=meta,
                              headers=self._headers(**{"Content-Type": "application/json; charset=UTF-8",
                                                       "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": mime}))
        session = headers.get("Location") or headers.get("location")
        if not session:
            raise YouTubeError("upload session did not return a Location")
        with open(video, "rb") as fh:
            payload = fh.read()
        _, _, raw = _http("PUT", session, data=payload, headers=self._headers(**{"Content-Type": mime, "Content-Length": str(size)}), timeout=1800)
        data = json.loads(raw)
        vid = data.get("id")
        if not vid:
            raise YouTubeError(f"upload returned no id: {str(data)[:300]}")
        log(f"youtube: uploaded {video.name} as {vid} ({'scheduled ' + iso(publish_at) if publish_at else privacy})")
        return {"id": vid, "url": f"https://youtu.be/{vid}", "status": "scheduled" if publish_at else privacy,
                "publish_at": iso(publish_at) if publish_at else None}

    def set_thumbnail(self, video_id: str, image: Path) -> None:
        mime = mimetypes.guess_type(str(image))[0] or "image/jpeg"
        _http("POST", f"{UPLOAD}/thumbnails/set?{urllib.parse.urlencode({'videoId': video_id})}",
              data=image.read_bytes(), headers=self._headers(**{"Content-Type": mime}))
        log(f"youtube: thumbnail set on {video_id}")

    def add_to_playlist(self, video_id: str, playlist_id: str) -> None:
        self._json("POST", "playlistItems", {"part": "snippet"},
                   {"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}})
        log(f"youtube: {video_id} added to playlist {playlist_id}")

    def video_status(self, video_id: str) -> dict:
        data = self._json("GET", "videos", {"part": "status,statistics", "id": video_id})
        items = data.get("items") or []
        if not items:
            return {"status": "removed"}
        st = items[0].get("status", {})
        return {"status": "sent" if st.get("privacyStatus") == "public" else st.get("privacyStatus"),
                "publish_at": st.get("publishAt"), "views": int(items[0].get("statistics", {}).get("viewCount", 0))}


def playlist_id(url: str | None) -> str | None:
    if not url:
        return None
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return (q.get("list") or [None])[0]
