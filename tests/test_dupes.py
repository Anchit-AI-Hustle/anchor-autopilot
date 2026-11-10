"""One song, one video (Anchit, 2026-11-10: "ensure old songs arent reuploaded again and again
... only unique videos and audios ... ensure duplicate ones are removed")."""
import numpy as np

from anchor import dupes, playlists


def v(i, title, dur="PT3M20S", privacy="public", published="2026-11-01T00:00:00Z"):
    return {"id": i, "title": title, "duration": dur, "privacy": privacy, "published": published}


VIDEOS = [
    v("NEW", "Outrun Your Shadow | Rap Techno | ANCHOR", published="2026-11-08T18:37:00Z"),
    v("OLD", "Outrun Your Shadow | Rap Techno | ANCHOR", published="2026-11-07T10:00:00Z"),
    v("RE1", "Spatula Solo | Hard Techno | ANCHOR", published="2026-11-03T21:42:49Z"),
    v("RE2", "Spatula Solo | Hard Techno | ANCHOR", published="2026-11-04T09:00:00Z"),
    v("S1", "Spatula Solo | Hard Techno | ANCHOR", dur="PT45S", published="2026-11-03T21:00:00Z"),
    v("S2", "Spatula Solo #shorts", dur="PT45S", published="2026-11-05T21:00:00Z"),
    v("AKA", "Mirror Track | Acid Techno | ANCHOR", published="2026-11-06T00:00:00Z"),
    v("ORIG", "First Track | Acid Techno | ANCHOR", published="2026-11-02T00:00:00Z"),
    v("ALIKE", "Afterburn | Hard Techno | ANCHOR"),
    v("PRIV", "Spatula Solo | Hard Techno | ANCHOR", privacy="private"),
]
CATALOG = {"drops": [{"id": "2026-11-03", "title": "Spatula Solo", "youtube_full_url": "https://youtu.be/RE1",
                      "youtube_short_url": "https://www.youtube.com/watch?v=S1"}]}
UPLOADS = {"uploads": [{"id": "lyricsync-2026-11-07", "youtube_url": "https://www.youtube.com/watch?v=NEW", "replaces": ["OLD"]}]}
CHANNEL = {"sound_alikes": {"Afterburn": "Grid Blade"}}
DUPES = {"audio_pairs": [
    {"duplicate": "2026-11-06", "of": "2026-11-02", "duplicate_title": "Mirror Track", "of_title": "First Track",
     "same_record": True, "score": {"envelope": 0.9, "sequence": 0.8}},
    {"duplicate": "2026-11-09", "of": "2026-09-12", "duplicate_title": "Afterburn", "of_title": "Grid Blade",
     "same_record": False, "score": {"envelope": 0.65, "sequence": 0.4}}]}


def test_each_song_keeps_one_full_video_and_one_short():
    r = dupes.audit(VIDEOS, CATALOG, UPLOADS, CHANNEL, DUPES)
    ids = {d["id"]: d for d in r["duplicates"]}
    assert r["canonical"]["outrunyourshadow"] == "NEW" and ids["OLD"]["why"].startswith("replaced")
    assert r["canonical"]["spatulasolo"] == "RE1" and ids["RE2"]["keep"] == "RE1"          # the recorded one stays
    assert "S1" not in ids and ids["S2"]["kind"] == "short" and ids["S2"]["keep"] == "S1"
    assert r["canonical"]["firsttrack"] == "ORIG" and ids["AKA"]["why"] == "same music as First Track | Acid Techno | ANCHOR"
    assert "ALIKE" not in ids, "a song that only sounds alike stays on the channel (out of the playlist)"
    assert "PRIV" not in ids, "a private video is not counted"
    assert {d["id"] for d in r["duplicate_full"]} == {"OLD", "RE2", "AKA"}


def test_duplicates_go_private_never_deleted():
    calls = []

    class Api:
        def set_privacy(self, vid, privacy):
            calls.append((vid, privacy))
            if vid == "RE2":
                raise RuntimeError('HTTP 403 {"reason": "quotaExceeded"}')

    r = dupes.audit(VIDEOS, CATALOG, UPLOADS, CHANNEL, DUPES)
    done = dupes.apply(Api(), r)
    assert all(p == "private" for _, p in calls) and not hasattr(Api, "delete")
    assert calls[-1][0] == "RE2" and "quota" in done["errors"][0]


def test_nothing_uploads_a_song_already_on_the_channel():
    assert dupes.is_reupload("Spatula Solo | Hard Techno | ANCHOR", VIDEOS) in {"RE1", "RE2"}
    assert dupes.is_reupload("Mirror Track | Acid Techno | ANCHOR", VIDEOS, {}, DUPES) is not None
    assert dupes.is_reupload("Brand New Song | Hard Tech | ANCHOR", VIDEOS) is None
    # a declared replacement of every copy may go up
    assert dupes.is_reupload("Outrun Your Shadow | Rap Techno | ANCHOR", VIDEOS, replaces=["NEW", "OLD"]) is None
    # a Short or a private copy is not "already on the channel"
    assert dupes.is_reupload("Lone Short", [v("X", "Lone Short", dur="PT45S"), v("Y", "Lone Short", privacy="private")]) is None


def test_the_playlist_holds_each_unique_song_once():
    r = dupes.audit(VIDEOS, CATALOG, UPLOADS, CHANNEL, DUPES)
    keep = set(r["canonical"].values())
    lists = {"MAIN": [{"item": "i1", "video": "OLD"}, {"item": "i2", "video": "NEW"}, {"item": "i3", "video": "S1"},
                      {"item": "i4", "video": "NEW"}]}
    p = playlists.plan(VIDEOS, lists, "MAIN", CHANNEL, keep)
    out = {x["item"] for x in p["remove"]}
    assert out == {"i1", "i3", "i4"}
    added = {x["id"] for x in p["add"]}
    assert added == keep - {"NEW", "ALIKE"} and "S2" not in added and "RE2" not in added


def test_the_same_music_is_found_by_its_prints(monkeypatch):
    from anchor import unique
    same = lambda x, y: {"envelope": 0.95 if x is y else 0.2, "sequence": 0.9 if x is y else 0.1}
    monkeypatch.setattr(unique, "similarity", same)
    a, c = {"env": np.zeros(3)}, {"env": np.ones(3)}
    b = a
    pairs = dupes.audio_pairs({"2026-11-01": a, "2026-11-05": b, "2026-11-03": c},
                              {"2026-11-01": "One", "2026-11-05": "Copy", "2026-11-03": "Other"})
    assert [(p["duplicate"], p["of"], p["same_record"]) for p in pairs] == [("2026-11-05", "2026-11-01", True)]
