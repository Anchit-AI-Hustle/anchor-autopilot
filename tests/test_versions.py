"""One version of every record everywhere: the edits, the build from local stand-ins for the
release and Suno files, the swap on a fake YouTube, and the plan in site/data/versions.json.
Nothing here touches the network."""
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from anchor import catalog as catmod
from anchor import craft, versions, youtube
from anchor.audio import SR, beat_phase, decode
from anchor.config import CATALOG_PATH, load_profile
from anchor.music import synth_techno, write_wav

BPM = 150
BAR = 240 / BPM


# ------------------------------------------------------------------------- edits
def test_weld_starts_the_second_take_at_its_mark_with_an_equal_power_overlap():
    a = np.full((SR * 10, 2), 0.5, np.float32)
    b = np.full((SR * 6, 2), 0.5, np.float32)
    out = versions.weld([a, b], [0.0, 8.0])
    assert len(out) == SR * 14                      # 8 s of a, then all of b
    mid = out[int(SR * 9)]                           # halfway through the 2 s overlap
    assert np.allclose(mid, 0.5 * 2 * np.sqrt(0.5), atol=1e-3)   # equal power, not a dip
    assert np.allclose(out[-1], 0.5)


def test_extend_adds_a_breakdown_and_a_repeat_that_are_whole_bars():
    x = synth_techno(64 * BAR + 1, BPM, 5).astype(np.float32)
    out = versions.extend(x, BPM, breakdown_from=(24, 32), before_bar=32, repeat=(32, 40), outro_bar=40)
    added = (len(out) - len(x)) / SR
    assert abs(added - 24 * BAR) < 0.01              # 16 bars of breakdown, 8 bars again
    phase = beat_phase(x.mean(axis=1), BPM)
    brk = out[int((phase + 32 * BAR) * SR):int((phase + 40 * BAR) * SR)]
    before = out[int((phase + 24 * BAR) * SR):int((phase + 32 * BAR) * SR)]
    lo = lambda y: np.abs(np.fft.rfft(y.mean(axis=1)))[: int(len(y) / SR * 100)].sum()   # noqa: E731, < 100 Hz
    assert lo(brk) < 0.1 * lo(before)                # first half of the breakdown: kick and sub out
    d = np.abs(np.diff(out.mean(axis=1)))
    assert d.max() < 3 * np.abs(np.diff(x.mean(axis=1))).max()    # no click at any cut


def test_the_short_is_found_again_inside_the_full_record():
    x = synth_techno(90, BPM, 7).astype(np.float32)
    x[int(40 * SR):int(52 * SR)] *= 0.2               # a breakdown gives the envelope a shape to match
    short = x[int(30 * SR):int(75 * SR)]
    start, match = versions.find_window(short, x)
    assert abs(start - 30.0) <= 0.1 and match > 0.95


def test_tame_fizz_turns_down_a_noise_wash_and_leaves_tonal_highs_alone():
    rng = np.random.default_rng(2)
    t = np.arange(SR * 6) / SR
    body = 0.3 * np.sin(2 * np.pi * 110 * t)
    wash = np.fft.irfft(np.fft.rfft(rng.standard_normal(len(t))) * (np.fft.rfftfreq(len(t), 1 / SR) > 4000), len(t))
    noisy = np.stack([body + 0.1 * wash] * 2, axis=1).astype(np.float32)
    tonal = np.stack([body + 0.1 * np.sin(2 * np.pi * 9000 * t)] * 2, axis=1).astype(np.float32)
    hi = lambda y: np.sum(np.abs(np.fft.rfft(y[SR:-SR, 0]))[int(7000 * 4):] ** 2)   # noqa: E731, 4 bins per Hz over 4 s
    out, info = craft.tame_fizz(noisy)
    assert info["frames_cut"] > 0.5 and 10 * np.log10(hi(noisy) / hi(out)) > 3
    same, info = craft.tame_fizz(tonal)
    assert info["frames_cut"] == 0 and np.allclose(same[SR:-SR], tonal[SR:-SR], atol=1e-3)
    band = lambda y, a, b: np.sum(np.abs(np.fft.rfft(y[SR:-SR, 0]))[4 * a:4 * b] ** 2)   # noqa: E731
    assert abs(10 * np.log10(band(out, 50, 3000) / band(noisy, 50, 3000))) < 0.05     # the body does not move
    assert abs(10 * np.log10(band(out, 4000, 5000) / band(noisy, 4000, 5000))) < 0.5  # nor the wash under 5 kHz


# ------------------------------------------------------------------------- build
def _stand_ins(tmp: Path, seconds: float = 70) -> dict:
    """The files build() downloads, made locally: a release FLAC, its cover and the old Short."""
    x = synth_techno(seconds, BPM, 11).astype(np.float32)
    x[int(26 * SR):int(38 * SR)] *= 0.15
    wav = tmp / "src.wav"
    write_wav(wav, x * 0.7)
    files = {"flac": tmp / "rel.flac", "cover": tmp / "cover.jpg", "short": tmp / "old-short.mp4"}
    run = lambda *a: subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)   # noqa: E731
    run("-i", str(wav), "-c:a", "flac", str(files["flac"]))
    run("-f", "lavfi", "-i", "color=c=0x223344:s=600x600", "-frames:v", "1", "-q:v", "2", str(files["cover"]))
    run("-f", "lavfi", "-i", "color=c=0x445566:s=270x480:r=30", "-ss", "20", "-t", "30", "-i", str(wav),
        "-map", "0:v", "-map", "1:a", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-b:a", "128k",
        str(files["short"]))
    return files


@pytest.fixture
def local_fetch(monkeypatch, tmp_path):
    files = _stand_ins(tmp_path)
    got = []

    def fetch(url, dst, min_bytes=50_000):
        got.append(url)
        dst.parent.mkdir(parents=True, exist_ok=True)
        key = "cover" if url.endswith("-cover.jpg") else "short" if "-short" in url else "flac"
        shutil.copy(files[key], dst)
        return dst

    monkeypatch.setattr(versions, "fetch", fetch)
    return got


DROP = {"id": "2026-09-13", "title": "Test Record", "date": "2026-09-13", "bpm": BPM, "lane_name": "Hypnotic Techno",
        "audio_url": "https://github.com/o/r/releases/download/drop-2026-09-13/ANCHOR-2026-09-13-test-record.mp3"}


def test_build_makes_one_master_and_a_short_cut_from_it(local_fetch, tmp_path):
    p = load_profile()
    entry = {"id": DROP["id"], "source": {"release": "drop-2026-09-13", "file": "ANCHOR-2026-09-13-test-record.flac"},
             "tame": True, "finish": False}
    meta = versions.build(p, entry, DROP, "o/r", tmp_path / "work")
    work = tmp_path / "work"
    assert local_fetch[0] == "https://github.com/o/r/releases/download/drop-2026-09-13/ANCHOR-2026-09-13-test-record-original.flac"
    assert meta["files"] == {"mp3": "ANCHOR-2026-09-13-test-record.mp3", "flac": "ANCHOR-2026-09-13-test-record.flac",
                             "short": "ANCHOR-2026-09-13-test-record-short.mp4"}
    assert abs(meta["loudness"]["input_i"] - float(p.music["loudness_lufs"])) < 0.6
    assert meta["loudness"]["input_tp"] <= float(p.music["true_peak_db"]) + 0.3
    assert abs(meta["short"]["start_s"] - 20.0) <= 0.2 and meta["short"]["match"] > 0.9
    assert not any("finishing pass" in n for n in meta["notes"]) and any("fizz" in n for n in meta["notes"])
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name",
                                       "-of", "json", str(work / meta["files"]["short"])], capture_output=True, text=True).stdout)
    assert sorted(s["codec_type"] for s in probe["streams"]) == ["audio", "video"]
    # the Short carries the new master's sound at the place the old one was cut from
    master = decode(work / "master.wav")
    short = decode(work / meta["files"]["short"])
    s = int(20.0 * SR) + SR * 5
    a, b = master[s:s + SR * 10].mean(axis=1), short[SR * 5:SR * 15].mean(axis=1)
    assert np.corrcoef(np.abs(a[::480]), np.abs(b[::480]))[0, 1] > 0.8
    assert json.loads((work / "meta.json").read_text())["id"] == DROP["id"]


def test_build_stops_when_the_old_short_is_not_in_the_new_record(local_fetch, tmp_path, monkeypatch):
    monkeypatch.setattr(versions, "find_window", lambda a, b: (0.0, 0.4))
    entry = {"id": DROP["id"], "source": {"release": "drop-2026-09-13", "file": "x.flac"}, "finish": False}
    with pytest.raises(RuntimeError, match="not found"):
        versions.build(load_profile(), entry, DROP, "o/r", tmp_path / "w")


# ----------------------------------------------------------------------- publish
class FakeChannel:
    def __init__(self):
        self.calls = []
        self.n = 0

    def videos(self, ids):
        self.calls.append(("videos", ids))
        return [{"id": "OLDFULL", "title": "Test Record | Hypnotic Techno 150 BPM | ANCHOR", "description": "Hypnotic Techno at 150 BPM.",
                 "tags": ["techno"], "categoryId": "10"},
                {"id": "OLDSHORT", "title": "Test Record #shorts", "description": "Hook line\n\nFull track: https://youtu.be/OLDFULL\n\n#techno",
                 "tags": ["shorts"], "categoryId": "10"}]

    def upload(self, path, **kw):
        self.n += 1
        self.calls.append(("upload", Path(path).name, kw))
        return {"id": f"NEW{self.n}", "url": f"https://youtu.be/NEW{self.n}", "status": "public"}

    def set_thumbnail(self, vid, path):
        self.calls.append(("thumb", vid))

    def add_to_playlist(self, vid, pl):
        self.calls.append(("playlist", vid, pl))

    def set_privacy(self, vid, privacy):
        self.calls.append(("privacy", vid, privacy))

    def __getattr__(self, name):                   # anything else, delete included, is a failure
        raise AssertionError(f"unexpected call {name}")


def test_publish_uploads_the_new_pair_with_the_old_words_and_sets_the_old_pair_private(monkeypatch, tmp_path):
    monkeypatch.setattr(versions, "fetch", lambda url, dst, min_bytes=0: (dst.write_bytes(b"jpg"), dst)[1])
    import anchor.video as video
    monkeypatch.setattr(video, "render_motion", lambda frame, audio, out, accent, **kw: out.write_bytes(b"mp4") or {})
    meta = {"id": DROP["id"], "title": "Test Record", "base": "b", "files": {"mp3": "b.mp3", "short": "b-short.mp4"}}
    entry = {"id": DROP["id"], "youtube": {"full": "OLDFULL", "short": "OLDSHORT"}}
    api = FakeChannel()
    pub = versions.publish(load_profile(), entry, meta, tmp_path, api=api)
    ups = [c for c in api.calls if c[0] == "upload"]
    assert [u[1] for u in ups] == ["b-full-169.mp4", "b-short.mp4"]
    assert ups[0][2]["title"] == "Test Record | Hypnotic Techno 150 BPM | ANCHOR" and ups[0][2]["tags"] == ["techno"]
    assert "Full track: https://youtu.be/NEW1" in ups[1][2]["description"] and "OLDFULL" not in ups[1][2]["description"]
    assert ups[1][2]["description"].startswith("Hook line") and ups[1][2]["description"].endswith("#techno")
    privacy = [c for c in api.calls if c[0] == "privacy"]
    assert privacy == [("privacy", "OLDFULL", "private"), ("privacy", "OLDSHORT", "private")]
    assert api.calls.index(privacy[0]) > api.calls.index(ups[1])      # the old ones go only once the new ones are up
    assert pub["full"] == "NEW1" and pub["short"] == "NEW2" and pub["replaced"] == ["OLDFULL", "OLDSHORT"]
    assert "publishing" not in entry


def test_a_publish_that_stopped_halfway_picks_up_without_a_second_upload(monkeypatch, tmp_path):
    import anchor.video as video
    monkeypatch.setattr(video, "render_motion", lambda *a, **kw: pytest.fail("the full video is already up"))
    meta = {"id": DROP["id"], "title": "Test Record", "base": "b", "files": {"mp3": "b.mp3", "short": "b-short.mp4"}}
    entry = {"id": DROP["id"], "youtube": {"full": "OLDFULL", "short": "OLDSHORT"},
             "publishing": {"full": {"id": "UP1", "url": "https://youtu.be/UP1"}, "private": []}}
    api = FakeChannel()
    pub = versions.publish(load_profile(), entry, meta, tmp_path, api=api)
    ups = [c for c in api.calls if c[0] == "upload"]
    assert len(ups) == 1 and ups[0][1] == "b-short.mp4" and "Full track: https://youtu.be/UP1" in ups[0][2]["description"]
    assert pub["full"] == "UP1" and [c[1] for c in api.calls if c[0] == "privacy"] == ["OLDFULL", "OLDSHORT"]


def test_a_rebuild_reads_the_kept_original_never_its_own_output(monkeypatch, tmp_path):
    import urllib.error
    asked = []

    def fetch(url, dst, min_bytes=50_000):
        asked.append(url.rsplit("/", 1)[-1])
        if url.endswith("-original.flac") and len(asked) == 1:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return dst

    monkeypatch.setattr(versions, "fetch", fetch)
    versions.release_fetch("o/r", "drop-x", "a.flac", tmp_path / "a.flac")
    versions.release_fetch("o/r", "drop-x", "a.flac", tmp_path / "a.flac")
    assert asked == ["a-original.flac", "a.flac", "a-original.flac"]
    assert versions.original("x-short.mp4") == "x-short-original.mp4"


def test_the_data_api_calls_for_a_swap(monkeypatch):
    calls = []

    def http(method, url, *, data=None, headers=None, timeout=120):
        calls.append((method, url, data))
        if url.startswith(youtube.TOKEN_URL):
            return 200, {}, json.dumps({"access_token": "at"}).encode()
        if method == "GET":
            return 200, {}, json.dumps({"items": [{"id": "A", "snippet": {"title": "T", "description": "D", "tags": ["x"], "categoryId": "10"}},
                                                  {"id": "B", "snippet": {"title": "S"}}]}).encode()
        return 200, {}, b"{}"

    monkeypatch.setattr(youtube, "_http", http)
    api = youtube.YouTube("c", "s", "r")
    assert api.videos(["A", "B"]) == [{"id": "A", "title": "T", "description": "D", "tags": ["x"], "categoryId": "10"},
                                      {"id": "B", "title": "S", "description": "", "tags": [], "categoryId": "10"}]
    api.set_privacy("A", "private")
    put = [c for c in calls if c[0] == "PUT"][-1]
    assert "part=status" in put[1]
    body = json.loads(put[2])
    assert body["id"] == "A" and body["status"]["privacyStatus"] == "private" and body["status"]["containsSyntheticMedia"] is True
    assert not any(c[0] == "DELETE" for c in calls)


# ------------------------------------------------------------------------ record
def test_record_writes_the_new_length_loudness_and_links():
    cat = {"drops": [{"id": DROP["id"], "duration_s": 150, "qc": {"lufs": -11.2}, "youtube_url": "https://www.youtube.com/watch?v=OLDSHORT",
                      "audio_url": DROP["audio_url"], "video_url": DROP["audio_url"].replace(".mp3", "-short.mp4"),
                      "short_url": "https://pages.example/media/x-short.mp4"}]}
    entry = {"id": DROP["id"]}
    meta = {"id": DROP["id"], "duration_s": 187.2, "loudness": {"input_i": -14.05, "input_tp": -1.8}, "built_at": "2026-09-23T18:53:01Z",
            "notes": ["n"], "short": {"start_s": 20.0}}
    versions.record(cat, entry, meta, None)
    d = cat["drops"][0]
    assert d["duration_s"] == 187.2 and d["qc"]["lufs"] == -14.05 and d["youtube_url"].endswith("OLDSHORT")
    assert entry["built"]["duration_s"] == 187.2 and "published" not in entry
    assert d["audio_url"] == DROP["audio_url"] + "?v=202609231853" and d["video_url"].endswith("-short.mp4?v=202609231853")
    assert d["short_url"] == "https://pages.example/media/x-short.mp4"          # not a release asset, left alone
    versions.record(cat, entry, meta, {"full": "NEW1", "short": "NEW2", "replaced": ["OLDFULL", "OLDSHORT"]})
    assert d["youtube_url"].endswith("v=NEW2") and d["youtube_full_url"].endswith("v=NEW1") and entry["published"]["full"] == "NEW1"
    kept = catmod.upsert({"drops": []}, {**d, "date": "2026-09-13", "title": "x"})["drops"][0]
    assert d["audio_url"].count("?v=") == 1                                    # a second pass does not stack marks
    assert kept["version"] == {"built_at": "2026-09-23T18:53:01Z", "notes": ["n"]} and kept["youtube_full_url"].endswith("NEW1")


def test_the_new_uploads_inherit_the_channel_facts_so_retitle_knows_them():
    ch = {"videos": {"OLDFULL": {"title": "T", "genre": "G", "bpm": 150, "kind": "video"},
                     "OLDSHORT": {"title": "T", "genre": "G", "bpm": 150, "kind": "short", "full": "OLDFULL"}}}
    versions.remap_channel(ch, {"full": "NEW1", "short": "NEW2", "replaced": ["OLDFULL", "OLDSHORT"]})
    v = ch["videos"]
    assert v["NEW1"]["kind"] == "video" and v["NEW2"]["full"] == "NEW1"
    assert v["OLDFULL"]["replaced_by"] == "NEW1" and v["OLDSHORT"]["replaced_by"] == "NEW2"


def test_pending_skips_what_is_done():
    data = {"records": [{"id": "a", "built": {}}, {"id": "b"}, {"id": "c", "built": {}, "published": {}}]}
    assert [e["id"] for e in versions.pending(data, "built")] == ["b"]
    assert [e["id"] for e in versions.pending(data, "published")] == ["a", "b"]


# -------------------------------------------------------------------- the plan
def test_the_plan_names_real_records_and_real_sources():
    plan = versions.load()
    cat = {d["id"]: d for d in json.loads(CATALOG_PATH.read_text())["drops"]}
    ids = [e["id"] for e in plan["records"]]
    assert ids and len(ids) == len(set(ids))
    for e in plan["records"]:
        assert e["id"] in cat, e["id"]
        for s in e["source"] if isinstance(e["source"], list) else [e["source"]]:
            assert ("suno" in s and len(s["suno"]) == 36) or (s["release"] == f"drop-{e['id']}" and s["file"].endswith(".flac"))
        assert set(e["youtube"]) == {"full", "short"} and all(len(v) == 11 for v in e["youtube"].values())
        if e.get("extend"):
            x = e["extend"]
            assert x["before_bar"] % 8 == 0 and (x["repeat"][1] - x["repeat"][0]) % 8 == 0 and x["outro_bar"] % 8 == 0
            assert (x["breakdown_from"][1] - x["breakdown_from"][0]) % 8 == 0     # whole phrases, so the grid holds
    pm = next(e for e in plan["records"] if e["title"] == "Project Mayhem")
    assert pm["tame"] is True and pm["finish"] is False and "extend" not in pm     # the song as it is, only cleaner


def test_a_new_master_is_printed_again_for_the_uniqueness_check(tmp_path):
    from anchor import unique
    wav = tmp_path / "a.wav"
    write_wav(wav, synth_techno(20, BPM, 4) * 0.5)
    cat = tmp_path / "catalog.json"
    # a local file stands in for the release; the fragment carries the version mark the way the query does online
    for url in (f"file://{wav}", f"file://{wav}#?v=202609231853"):
        cat.write_text(json.dumps({"drops": [{"id": "2026-09-13", "audio_url": url}]}))
        assert "2026-09-13" in unique.released_prints(cat, tmp_path / "prints")
    assert {p.name for p in (tmp_path / "prints").glob("*.npz")} == {"2026-09-13.npz", "2026-09-13-v202609231853.npz"}
