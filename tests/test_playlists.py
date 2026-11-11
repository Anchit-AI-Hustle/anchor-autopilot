"""Playlists stay clean: every public video lands in ANCHOR, no video sits in a playlist twice,
and nothing you left out stays in one. A fake YouTube; nothing touches the network."""
import json
from pathlib import Path

from anchor import playlists
from anchor.config import load_profile
from anchor.unique import sounds_alike

PROFILE = load_profile()
MAIN = "PLSA3gW62zSYE"


def vid(i, title, secs, privacy="public"):
    return {"id": i, "title": title, "duration": f"PT{secs // 60}M{secs % 60}S", "privacy": privacy}


# the uploads list is newest first, as the Data API returns it
VIDEOS = [vid("F9", "Cold Bunker | Rawstyle Hybrid 155 BPM | ANCHOR", 150),
          vid("N1", "Null Monolith | Dark Techno 146 BPM | ANCHOR", 150),
          vid("S1", "Cold Bunker", 45),
          vid("K2", "Kindness Needs Truth (Lyric Video) | ANCHOR", 254),
          vid("P0", "Private One", 200, privacy="private"),
          vid("A1", "Afterburn", 150),
          vid("K1", "Kindness Needs Truth", 254),
          vid("G1", "Grid Blade", 150),
          vid("R1", "Rupture Pulse", 190)]
CHANNEL = {"withdrawn": ["Rupture Pulse"], "sound_alikes": {"Afterburn": "Grid Blade", "Null Monolith": "Grid Blade"}}


class FakeYouTube:
    def __init__(self, lists):
        self.lists, self.added, self.removed = lists, [], []

    def channel_videos(self, cid):
        return VIDEOS

    def playlists(self, cid):
        return [{"id": p, "title": p} for p in self.lists]

    def playlist_items(self, pl):
        return self.lists[pl]

    def add_to_playlist(self, v, pl):
        self.added.append((v, pl))

    def remove_from_playlist(self, item):
        self.removed.append(item)


def lists():
    return {MAIN: [{"item": "m1", "video": "G1"}, {"item": "m2", "video": "A1"}, {"item": "m3", "video": "G1"},
                   {"item": "m4", "video": "S1"}, {"item": "m5", "video": "R1"}],
            "PLrave": [{"item": "r1", "video": "A1"}, {"item": "r2", "video": "K1"}, {"item": "r3", "video": "gone"}]}


def test_plan_adds_every_public_video_once_and_takes_out_twins_and_left_out_songs():
    p = playlists.plan(VIDEOS, lists(), MAIN, CHANNEL)
    assert [(r["item"], r["why"]) for r in p["remove"]] == [("m2", "left out"), ("m3", "same video twice"),
                                                              ("m5", "left out"), ("r1", "left out")]
    # oldest first; both Kindness Needs Truth videos; the private video, the withdrawn and the
    # sound-alikes never go in (the Short S1 is already there)
    assert [v["id"] for v in p["add"]] == ["K1", "K2", "F9"]


def test_each_unique_song_goes_in_once():
    """Anchit, 2026-11-10: "only unique videos and audios are there in the playlist": the song's
    one full video, never a second upload of the same music or its Short."""
    from anchor import dupes
    videos = [vid("L1", "Outrun Your Shadow (Lyric Video) | ANCHOR", 276), vid("S2", "Outrun Your Shadow", 40),
              vid("O2", "Outrun Your Shadow | ANCHOR", 276), vid("O1", "Outrun Your Shadow | ANCHOR", 276),
              vid("S1", "Cold Bunker", 45)]       # newest first, as the Data API lists them
    keep = set(dupes.audit(videos, {}, {}, {}, {})["canonical"].values())
    assert keep == {"O1"}
    p = playlists.plan(videos, {MAIN: []}, MAIN, {}, keep)
    assert [v["id"] for v in p["add"]] == ["O1"]
    p = playlists.plan(videos, {MAIN: [{"item": "x", "video": "O1"}, {"item": "y", "video": "O2"}]}, MAIN, {}, keep)
    assert [r["item"] for r in p["remove"]] == ["y"] and p["add"] == []


def test_a_spent_quota_is_a_warning_and_the_next_run_catches_up(monkeypatch, capsys):
    from anchor import __main__ as cli
    from anchor.youtube import YouTubeError

    def spent(*a, **k):
        raise YouTubeError('HTTP 403 GET channels: {"reason": "quotaExceeded"}')

    monkeypatch.setattr(playlists, "run", spent)
    monkeypatch.setattr("sys.argv", ["anchor", "playlists"])
    assert cli.main() == 0
    assert "quota" in capsys.readouterr().out


def test_run_applies_the_plan_and_never_deletes_a_video(tmp_path):
    ch = tmp_path / "channel.json"
    ch.write_text(json.dumps(CHANNEL))
    yt = FakeYouTube(lists())
    out = playlists.run(PROFILE, api=yt, channel_path=ch)
    # the Short S1 leaves ANCHOR; Kindness Needs Truth goes in once (its lyric video K2 is the same music)
    assert yt.removed == ["m2", "m3", "m4", "m5", "r1"]
    assert yt.added == [("K1", MAIN), ("F9", MAIN)]
    assert not out["errors"] and len(out["added"]) == 2
    dry = FakeYouTube(lists())
    playlists.run(PROFILE, api=dry, channel_path=ch, dry_run=True)
    assert not dry.added and not dry.removed


def test_the_live_channel_file_keeps_the_sound_alikes_out():
    ch = json.loads((Path(__file__).parent.parent / "site/data/channel.json").read_text())
    assert set(ch["sound_alikes"]) == {"Afterburn", "Null Monolith"}
    assert "Rupture Pulse" in ch["withdrawn"]


def test_a_new_take_this_close_to_a_released_record_is_sent_back():
    assert sounds_alike({"envelope": 0.43, "sequence": 0.70})      # Null Monolith against Grid Blade
    assert sounds_alike({"envelope": 0.65, "sequence": 0.33})      # Afterburn against Grid Blade
    assert not sounds_alike({"envelope": 0.35, "sequence": 0.53})  # Rogue Frequency against Null Monolith


def test_a_side_playlist_youtube_cannot_find_never_stops_the_sync(tmp_path, monkeypatch):
    # 2026-11-11 11:24: one 404 playlistNotFound stopped the whole pass; the next run was fine
    monkeypatch.setattr("time.sleep", lambda s: None)
    ch = tmp_path / "channel.json"
    ch.write_text(json.dumps(CHANNEL))

    class Flaky(FakeYouTube):
        calls = 0

        def playlist_items(self, pl):
            if pl == "PLrave":
                Flaky.calls += 1
                raise RuntimeError("HTTP 404 playlistNotFound")
            return super().playlist_items(pl)

    yt = Flaky(lists())
    out = playlists.run(PROFILE, api=yt, channel_path=ch)
    assert Flaky.calls == 2                       # asked again once
    assert ("K1", MAIN) in yt.added and "r1" not in yt.removed
    assert out["errors"] and "PLrave" in out["errors"][0]


def test_the_main_playlist_failing_twice_still_fails_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    ch = tmp_path / "channel.json"
    ch.write_text(json.dumps(CHANNEL))

    class Down(FakeYouTube):
        def playlist_items(self, pl):
            raise RuntimeError("HTTP 404 playlistNotFound")

    import pytest
    with pytest.raises(RuntimeError):
        playlists.run(PROFILE, api=Down(lists()), channel_path=ch)
