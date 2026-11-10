"""A spent YouTube quota is a warning, not a failed run: the notice goes to stderr and stdout
stays the JSON the playlist and retitle workflows read (2026-11-10: both runs failed on it)."""
import json

from anchor import __main__ as cli
from anchor.youtube import YouTubeError


def _spent(*a, **k):
    raise YouTubeError('HTTP 403 GET playlistItems: {"reason": "quotaExceeded"}')


def test_playlists_quota_keeps_stdout_json(monkeypatch, capsys):
    from anchor import playlists
    monkeypatch.setattr(playlists, "run", _spent)
    monkeypatch.setattr("sys.argv", ["anchor", "playlists"])
    assert cli.main() == 0
    out, err = capsys.readouterr()
    assert json.loads(out) == {"skipped": "quota"} and "quota" in err


def test_retitle_quota_keeps_stdout_json(monkeypatch, capsys):
    from anchor import retitle
    monkeypatch.setattr(retitle, "run", _spent)
    monkeypatch.setattr("sys.argv", ["anchor", "retitle"])
    assert cli.main() in (0, None)
    out, err = capsys.readouterr()
    r = json.loads(out)
    assert r["skipped"] == "quota" and r["changed"] == [] and "quota" in err
