"""Playlists stay clean: every full video lands in ANCHOR, no song sits in a playlist twice,
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


def test_plan_adds_every_full_video_once_and_takes_out_twins_and_left_out_songs():
    p = playlists.plan(VIDEOS, lists(), MAIN, CHANNEL)
    assert [(r["item"], r["why"]) for r in p["remove"]] == [("m2", "left out"), ("m3", "same song twice"),
                                                              ("m5", "left out"), ("r1", "left out")]
    # oldest first; the Short, the private video, the withdrawn and the sound-alikes never go in
    assert [v["id"] for v in p["add"]] == ["K1", "K2", "F9"]


def test_run_applies_the_plan_and_never_deletes_a_video(tmp_path):
    ch = tmp_path / "channel.json"
    ch.write_text(json.dumps(CHANNEL))
    yt = FakeYouTube(lists())
    out = playlists.run(PROFILE, api=yt, channel_path=ch)
    assert yt.removed == ["m2", "m3", "m5", "r1"]
    assert yt.added == [("K1", MAIN), ("K2", MAIN), ("F9", MAIN)]
    assert not out["errors"] and len(out["added"]) == 3
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
