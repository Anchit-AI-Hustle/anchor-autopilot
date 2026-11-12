"""A song goes out once, under any name (Anchit, 2026-11-11: "last few videos were duplicates of
an older song - ensure unique new generations each and every time"). Pressure Spiral was on the
channel since September and went out again on 11-10 as "Start It Tonight"; New Beginnings went
out as "Doors Blown Open" and was queued again the next day."""
import json

from anchor import dupes, queue


def test_a_song_already_out_under_another_name_is_never_queued_again(tmp_path, monkeypatch):
    from anchor.config import ROOT
    monkeypatch.setattr("anchor.config.CATALOG_PATH", ROOT / "site" / "data" / "catalog.json")
    q = tmp_path / "queue"
    q.mkdir()
    (q / "queue.json").write_text("{}")
    # the live records: Pressure Spiral (channel since September and drop 2026-11-10) and
    # New Beginnings (drop 2026-11-09 as Doors Blown Open), queued again under new file names
    assert queue._already_posted("41-pressure-spiral-56f381b9.m4a", "Pressure Spiral", q)
    assert queue._already_posted("42-new-beginnings-219cedc0.m4a", "New Beginnings", q)
    assert queue._already_posted("43-renamed-take-219cedc0.m4a", "A Brand New Name", q), "same Suno song id"
    # a song never posted under any name still goes out
    assert not queue._already_posted("44-a-song-never-posted-0badf00d.m4a", "Zephyr Quokka Lantern", q)


def test_posted_titles_know_every_name_a_song_went_out_as(tmp_path):
    (tmp_path / "catalog.json").write_text(json.dumps({"drops": [
        {"id": "2026-11-10", "title": "Start It Tonight", "engine": {"name": "queue", "source_file": "36-pressure-spiral-56f381b9.m4a"}}]}))
    (tmp_path / "channel.json").write_text(json.dumps({"videos": {"x": {"title": "Old Song | Hard Techno | ANCHOR"}}}))
    names = queue.posted_titles(tmp_path / "catalog.json")
    assert {"Start It Tonight", "Pressure Spiral", "Old Song"} <= set(names)
    assert queue.posted_suno_ids(tmp_path / "catalog.json") == {"56f381b9"}


def v(i, title, published, secs=200):
    return {"id": i, "title": title, "privacy": "public", "duration": f"PT{secs // 60}M{secs % 60}S", "published": published}


def test_the_renamed_repost_goes_private_and_the_original_stays():
    catalog = {"drops": [{"id": "2026-11-10", "title": "Start It Tonight", "youtube_url": "https://youtu.be/NEW",
                          "engine": {"name": "queue", "source_file": "36-pressure-spiral-56f381b9.m4a"}}]}
    videos = [v("NEW", "Start It Tonight | Hard Groove Techno | ANCHOR", "2026-11-10T12:20:00Z"),
              v("OLD", "Pressure Spiral | Hard Techno | ANCHOR", "2026-09-20T10:00:00Z")]
    r = dupes.audit(videos, catalog, {}, {}, {})
    assert [d["id"] for d in r["duplicate_full"]] == ["NEW"]
    assert dupes.is_reupload("Pressure Spiral | Hard Techno | ANCHOR", videos[1:], catalog=catalog) == "OLD"
    assert dupes.is_reupload("Start It Tonight | Hard Groove Techno | ANCHOR", videos[1:], catalog=catalog) == "OLD"
