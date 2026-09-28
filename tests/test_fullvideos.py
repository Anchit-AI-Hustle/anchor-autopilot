"""Every Short has its full track on the channel: the plan, the backfill on a fake YouTube, the
Short's link, and a real render of the full video from a local stand-in for the release.
Nothing here touches the network."""
import json
import shutil
from pathlib import Path

from anchor import fullvideos
from anchor.config import load_profile
from anchor.music import synth_techno, write_wav
from anchor.util import run as sh

PROFILE = load_profile()


def drop(day, title, short, **kw):
    return {"id": day, "date": day, "title": title, "lane": PROFILE.lanes[0].id, "bpm": 150, "accent": "#d8742f",
            "youtube_url": f"https://www.youtube.com/watch?v={short}",
            "audio_url": f"https://github.com/o/r/releases/download/drop-{day}/ANCHOR-{day}-x.mp3", **kw}


def vid(i, title, secs, privacy="public", desc=""):
    return {"id": i, "title": title, "duration": f"PT{secs // 60}M{secs % 60}S", "privacy": privacy,
            "description": desc, "tags": [], "categoryId": "10"}


class FakeYouTube:
    def __init__(self, videos):
        self.list, self.uploads, self.updates, self.thumbs, self.playlist = videos, [], {}, [], []

    def channel_videos(self, channel_id):
        return self.list

    def upload(self, video, **kw):
        assert Path(video).exists()
        self.uploads.append(kw)
        return {"id": f"NEW{len(self.uploads)}", "url": f"https://youtu.be/NEW{len(self.uploads)}", "status": "public"}

    def update_video(self, video, *, title, description, tags=None):
        self.updates[video["id"]] = description

    def set_thumbnail(self, vid, image):
        self.thumbs.append(vid)

    def add_to_playlist(self, vid, pl):
        self.playlist.append(vid)


def catalog_with(tmp_path, drops, legacy=(), channel=None):
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps({"drops": list(drops), "legacy": list(legacy)}))
    (tmp_path / "channel.json").write_text(json.dumps(channel or {"videos": {}}, indent=1))
    return cat


# --------------------------------------------------------------------------- plan
def test_seconds_reads_youtube_durations():
    assert fullvideos.seconds("PT2M34S") == 154
    assert fullvideos.seconds("PT45S") == 45
    assert fullvideos.seconds("PT1H0M1S") == 3601
    assert fullvideos.seconds(None) == 0


def test_plan_sorts_every_short_and_never_takes_a_short_for_a_full_track():
    cat = {"drops": [drop("2026-09-27", "Overload Protocol", "S1"),
                     drop("2026-09-20", "Rupture Pulse", "S2"),
                     drop("2026-09-22", "Horizon Engine", "S3"),
                     drop("2026-09-19", "Feral Machine", "S4", youtube_full_url="https://www.youtube.com/watch?v=F4")],
           "legacy": [{"title": "Pull Under", "youtube_url": "https://www.youtube.com/shorts/L1"}]}
    videos = [vid("S1", "Overload Protocol", 45), vid("S2", "Rupture Pulse", 45),
              vid("F2", "Rupture Pulse | Industrial Hard Techno 154 BPM | ANCHOR", 190),
              vid("S3", "Horizon Engine", 45, privacy="private"), vid("S4", "Feral Machine", 45),
              vid("F4", "Feral Machine", 170), vid("L1", "Pull Under", 58),
              vid("X9", "Overload Protocol", 50)]             # a second Short with the same name is not its full track
    p = fullvideos.plan(cat, videos)
    assert [r["title"] for r in p["todo"]] == ["Overload Protocol"]
    assert [(r["title"], v["id"]) for r, v in p["found"]] == [("Rupture Pulse", "F2")]
    assert [r["title"] for r in p["linked"]] == ["Feral Machine"]
    assert [r["title"] for r in p["not_public"]] == ["Horizon Engine"]
    assert [r["title"] for r in p["no_audio"]] == ["Pull Under"]


def test_plan_includes_the_hand_made_shorts_channel_json_knows():
    channel = {"videos": {"H1": {"title": "Overload The Human Eye", "genre": "Cyberpunk Hard Techno", "bpm": None, "kind": "short"},
                          "V1": {"title": "Pressure Spiral", "genre": "Industrial Techno", "bpm": 150, "kind": "video"}}}
    p = fullvideos.plan({"drops": []}, [vid("H1", "Overload The Human Eye", 40), vid("V1", "Pressure Spiral", 200)], channel)
    assert [r["title"] for r in p["no_audio"]] == ["Overload The Human Eye"]
    assert not p["found"] and not p["todo"]


def test_short_body_keeps_the_records_words_and_drops_links_and_footer():
    desc = ("Industrial Hard Techno at 154 BPM. An ANCHOR original, free download below.\n\n"
            "Steel on steel, and a drop that does not ask.\n\n"
            "Full track: https://youtu.be/x\nAll tracks: https://y\n\n#techno #shorts")
    assert fullvideos.short_body(desc) == "Steel on steel, and a drop that does not ask."
    assert fullvideos.short_body("#techno #shorts") is None


def test_link_short_adds_the_full_track_once():
    api = FakeYouTube([])
    short = vid("S1", "X", 45, desc="line\n\nbody\n\n#shorts")
    assert fullvideos.link_short(api, short, "https://www.youtube.com/watch?v=F1")
    assert "Full track: https://www.youtube.com/watch?v=F1" in api.updates["S1"]
    short["description"] = api.updates["S1"]
    assert not fullvideos.link_short(api, short, "https://www.youtube.com/watch?v=F1")
    old = vid("S2", "X", 45, desc="a\n\nFull track: https://www.youtube.com/@AT_ANCHOR/videos\n\n#shorts")
    fullvideos.link_short(api, old, "https://www.youtube.com/watch?v=F2")
    assert api.updates["S2"].count("Full track:") == 1 and "watch?v=F2" in api.updates["S2"]


# ---------------------------------------------------------------------------- run
def test_run_uploads_links_and_records_each_track_and_stops_at_the_limit(tmp_path, monkeypatch):
    drops = [drop("2026-09-27", "Overload Protocol", "S1"), drop("2026-09-26", "Detonate Iron", "S2"),
             drop("2026-09-25", "Rogue Frequency", "S3"), drop("2026-09-20", "Rupture Pulse", "S4")]
    cat = catalog_with(tmp_path, drops)
    api = FakeYouTube([vid("S1", "Overload Protocol", 45, desc="Hypnotic Techno at 149 BPM. An ANCHOR original, free download below.\n\nOverload\n\nWarehouse lights out, one loop until the floor gives.\n\n#shorts"),
                       vid("S2", "Detonate Iron", 45), vid("S3", "Rogue Frequency", 45), vid("S4", "Rupture Pulse", 45),
                       vid("F4", "Rupture Pulse | Industrial Hard Techno 154 BPM | ANCHOR", 190)])
    built = []

    def fake_build(profile, r, repo, work):
        work.mkdir(parents=True, exist_ok=True)
        (work / "v.mp4").write_bytes(b"v")
        (work / "f.jpg").write_bytes(b"f")
        built.append(r["title"])
        return work / "v.mp4", work / "f.jpg"

    monkeypatch.setattr(fullvideos, "build", fake_build)
    out = fullvideos.run(PROFILE, repo="o/r", work=tmp_path / "w", limit=2, api=api, catalog_path=cat)
    assert built == ["Overload Protocol", "Detonate Iron"]
    assert out["uploaded"] == ["Overload Protocol -> NEW1", "Detonate Iron -> NEW2"]
    assert out["left"] == ["Rogue Frequency"]
    assert out["linked_existing"] == ["Rupture Pulse -> F4"]
    saved = {d["title"]: d.get("youtube_full_url") for d in json.loads(cat.read_text())["drops"]}
    assert saved == {"Overload Protocol": "https://www.youtube.com/watch?v=NEW1",
                     "Detonate Iron": "https://www.youtube.com/watch?v=NEW2",
                     "Rogue Frequency": None, "Rupture Pulse": "https://www.youtube.com/watch?v=F4"}
    first = api.uploads[0]
    assert first["title"].startswith("Overload Protocol | ") and first["title"].endswith("| ANCHOR")
    assert "Warehouse lights out, one loop until the floor gives." in first["description"] and "#shorts" not in first["description"]
    assert first["privacy"] == "public" and first["ai_generated"] is True and first["notify"] is False
    assert set(api.updates) == {"S1", "S2", "S4"}                 # every Short now points at its full track
    assert api.thumbs == ["NEW1", "NEW2"] and api.playlist == ["NEW1", "NEW2"]
    # the next run picks up where this one stopped and uploads nothing twice
    api.list += [vid("NEW1", "Overload Protocol | x | ANCHOR", 150), vid("NEW2", "Detonate Iron | x | ANCHOR", 150)]
    out2 = fullvideos.run(PROFILE, repo="o/r", work=tmp_path / "w", limit=2, api=api, catalog_path=cat)
    assert out2["uploaded"] == ["Rogue Frequency -> NEW3"] and len(api.uploads) == 3


def test_one_failed_build_never_stops_the_rest(tmp_path, monkeypatch):
    cat = catalog_with(tmp_path, [drop("2026-09-27", "A One", "S1"), drop("2026-09-26", "B Two", "S2")])
    api = FakeYouTube([vid("S1", "A One", 45), vid("S2", "B Two", 45)])

    def fake_build(profile, r, repo, work):
        if r["title"] == "A One":
            raise RuntimeError("release asset missing")
        work.mkdir(parents=True, exist_ok=True)
        (work / "v.mp4").write_bytes(b"v")
        return work / "v.mp4", work / "v.mp4"

    monkeypatch.setattr(fullvideos, "build", fake_build)
    out = fullvideos.run(PROFILE, repo="o/r", work=tmp_path / "w", api=api, catalog_path=cat)
    assert out["errors"] == ["A One: release asset missing"] and out["uploaded"] == ["B Two -> NEW1"]


def test_a_found_hand_made_short_is_recorded_in_channel_json(tmp_path):
    channel = {"videos": {"H1": {"title": "Time To Peak", "genre": "Hard Techno", "bpm": None, "kind": "short"}}}
    cat = catalog_with(tmp_path, [], channel=channel)
    api = FakeYouTube([vid("H1", "Time To Peak", 40), vid("V1", "Time To Peak | Hard Techno | ANCHOR", 210)])
    out = fullvideos.run(PROFILE, repo="o/r", work=tmp_path / "w", api=api, catalog_path=cat)
    assert out["linked_existing"] == ["Time To Peak -> V1"]
    saved = json.loads((tmp_path / "channel.json").read_text())
    assert saved["videos"]["H1"]["full_url"] == "https://www.youtube.com/watch?v=V1"
    assert (tmp_path / "channel.json").read_text().startswith('{\n "videos"')      # the file keeps its layout


def test_dry_run_changes_nothing(tmp_path):
    cat = catalog_with(tmp_path, [drop("2026-09-27", "A One", "S1")])
    before = cat.read_text()
    api = FakeYouTube([vid("S1", "A One", 45)])
    out = fullvideos.run(PROFILE, repo="o/r", work=tmp_path / "w", api=api, catalog_path=cat, dry_run=True)
    assert out["left"] == ["A One"] and not api.uploads and not api.updates and cat.read_text() == before


def test_build_renders_the_full_track_from_the_released_master(tmp_path, monkeypatch):
    """The real render: a synthetic 20 s master and a cover stand in for the release assets."""
    src = tmp_path / "src"
    src.mkdir()
    wav = src / "m.wav"
    write_wav(wav, synth_techno(20.0, 150, 3) * 0.5)
    mp3 = src / "ANCHOR-2026-09-27-x.mp3"
    sh(["ffmpeg", "-y", "-v", "error", "-i", wav, "-b:a", "192k", mp3], quiet=True)
    cover = src / "ANCHOR-2026-09-27-x-cover.jpg"
    sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x802010:s=1400x1400", "-frames:v", "1", cover], quiet=True)

    def fake_fetch(url, dst, min_bytes=50_000):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src / url.rsplit("/", 1)[-1], dst)
        return dst

    monkeypatch.setattr(fullvideos, "fetch", fake_fetch)
    video, frame = fullvideos.build(PROFILE, drop("2026-09-27", "Overload Protocol", "S1"), "o/r", tmp_path / "w")
    from anchor.video import media_summary
    info = media_summary(video)
    assert abs(info["duration"] - 20.0) < 1.0
    assert info["width"] == 1920 and info["height"] == 1080
    assert frame.exists()


def test_raw_art_redraws_the_clean_artwork_behind_a_released_cover(tmp_path):
    """A cover redrawn once (seed + 1) is still found; a cover it did not draw is not."""
    from anchor.art import make_cover
    fam = PROFILE.families[0]
    r = {"title": "Null Monolith", "family": fam.id, "seed": 1948294709, "art_source": "procedural"}
    make_cover(fam, {**r, "seed": r["seed"] + 1}, PROFILE.artist["name"], tmp_path / "c", "procedural")
    got = fullvideos.raw_art(PROFILE, r, tmp_path / "c" / "cover.jpg", tmp_path / "raw.jpg")
    assert got == tmp_path / "raw.jpg"
    from PIL import Image, ImageChops, ImageStat
    same = ImageChops.difference(Image.open(got).convert("RGB").resize((128, 128)),
                                 Image.open(tmp_path / "c" / "cover_art_raw.jpg").convert("RGB").resize((128, 128)))
    assert max(ImageStat.Stat(same).mean) < 4
    other = tmp_path / "other.jpg"
    Image.new("RGB", (1440, 1440), (20, 200, 40)).save(other)
    assert fullvideos.raw_art(PROFILE, r, other, tmp_path / "raw2.jpg") is None
    assert fullvideos.raw_art(PROFILE, {**r, "art_source": "cloudflare-flux-1-schnell"}, other, tmp_path / "raw3.jpg") is None
