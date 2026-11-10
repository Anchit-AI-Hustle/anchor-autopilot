"""Retry legs YouTube reports as needing nothing more (already in the playlist, old video gone)
are done, and the entry is marked replaced (2026-11-10, Outrun Your Shadow)."""
from anchor import uploads
from anchor.youtube import YouTubeError


class Api:
    def add_to_playlist(self, vid, pl):
        raise YouTubeError('HTTP 409 POST playlistItems: {"message": "Video already in playlist."}')

    def set_privacy(self, vid, status):
        if vid == "gone":
            raise YouTubeError("HTTP 404 PUT videos: {}")
        raise YouTubeError("HTTP 403 PUT videos: quotaExceeded")


def test_done_legs_leave_the_retry_list(tmp_path):
    e = {"id": "x", "youtube_url": "https://www.youtube.com/watch?v=new"}
    done = {"private": []}
    yt = {"playlist_url": "https://www.youtube.com/playlist?list=PLabc"}
    left = uploads._finish(Api(), e, "o/r", tmp_path, yt, done, ["playlist", "private gone", "private still"])
    assert left == ["private still"]                 # a real failure (quota) is still retried
    assert uploads._already_done("thumbnail", "HTTP 404") is False
