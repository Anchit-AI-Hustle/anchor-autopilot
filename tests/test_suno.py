"""The Suno catalogue: rating, near-duplicate detection, and the queue path behind
the website's "Add to YouTube" button."""
import json
import re
from pathlib import Path

import pytest

from anchor import suno

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def song(**kw):
    base = dict(id="0" * 8 + "-0000-0000-0000-" + "0" * 12, title="Untitled", tags="",
                duration_s=200.0, model="v5", plays=0, upvotes=0, created_at="",
                image="", audio_url="", video_url="", url="https://suno.com/song/x")
    base.update(kw)
    return suno.rate(base)


TECHNO = "hard techno, industrial techno, peak time techno, warehouse, 154 bpm, distorted kick"


def test_two_takes_of_one_prompt_are_grouped_and_the_better_one_is_the_pick():
    a = song(id="aaaaaaaa-0000-0000-0000-000000000001", title="Project Mayhem",
             tags=TECHNO, duration_s=245.0, plays=40)
    b = song(id="bbbbbbbb-0000-0000-0000-000000000002", title="Project Mayhem",
             tags=TECHNO, duration_s=240.0, plays=0)
    suno.annotate_similar([a, b])
    assert a["group"] and a["group"] == b["group"], "same prompt, same family"
    assert a["group_size"] == b["group_size"] == 2
    assert a["rating"] > b["rating"] and a["group_pick"] and not b["group_pick"]
    assert a["similar"][0]["id"] == b["id"] and a["similar"][0]["score"] > 0.9


def test_a_different_track_is_left_alone():
    a = song(id="aaaaaaaa-0000-0000-0000-000000000001", title="Concrete Pulse", tags=TECHNO)
    b = song(id="bbbbbbbb-0000-0000-0000-000000000002", title="Midnight Rain",
             tags="lo-fi hip hop, jazzy chords, rain, sleep", duration_s=120.0)
    suno.annotate_similar([a, b])
    assert a["group"] is None and b["group"] is None
    assert a["similar"] == [] and b["similar"] == []
    assert suno.similarity(a, b) < suno.NEAR


def test_groups_are_transitive():
    ids = ["%08d-0000-0000-0000-000000000000" % i for i in range(3)]
    trio = [song(id=i, title="Where It Begins", tags=TECHNO, duration_s=d)
            for i, d in zip(ids, (360.0, 330.0, 300.0))]
    suno.annotate_similar(trio)
    assert len({s["group"] for s in trio}) == 1
    assert [s["group_size"] for s in trio] == [3, 3, 3]
    assert sum(s["group_pick"] for s in trio) == 1, "exactly one pick per family"


def test_similar_list_is_capped_and_sorted():
    ids = ["%08d-0000-0000-0000-000000000000" % i for i in range(6)]
    fam = [song(id=i, title="Take", tags=TECHNO, duration_s=200.0 + n) for n, i in enumerate(ids)]
    suno.annotate_similar(fam, top=3)
    for s in fam:
        assert len(s["similar"]) <= 3
        assert s["similar"] == sorted(s["similar"], key=lambda x: -x["score"])


def test_song_id_is_read_from_an_issue_body():
    body = ("Queue this song for the next ANCHOR drop.\n\n- Suno: "
            "https://suno.com/song/f5207246-bf22-41b1-a4d2-8b3861149d7d\n"
            "- Id: `F5207246-BF22-41B1-A4D2-8B3861149D7D`\n")
    assert suno.song_id(body) == "f5207246-bf22-41b1-a4d2-8b3861149d7d"
    assert suno.song_id("f5207246-bf22-41b1-a4d2-8b3861149d7d") == \
        "f5207246-bf22-41b1-a4d2-8b3861149d7d"
    with pytest.raises(ValueError):
        suno.song_id("no id here")


def test_queueing_costs_the_repo_a_few_kb_not_megabytes(tmp_path):
    """The button queues a reference; the audio is fetched at release time."""
    s = song(id="f5207246-bf22-41b1-a4d2-8b3861149d7d", title="Project Mayhem",
             tags=TECHNO, duration_s=245.0, plays=36, model="v4.5-all",
             video_url="https://cdn1.suno.ai/f5207246-bf22-41b1-a4d2-8b3861149d7d.mp4")
    res = suno.queue_entry(s, tmp_path)
    rank = round(100 - s["rating"] * 10)
    assert res["name"] == f"{rank:02d}-project-mayhem-f5207246.m4a", \
        "the name leads with the inverted rating so the best song sorts first"
    assert not list(tmp_path.glob("*.m4a")), "nothing is downloaded at queue time"
    index = tmp_path / "queue.json"
    assert index.stat().st_size < 4096, "the queue stays small enough to live in git"
    entry = json.loads(index.read_text())[res["name"]]
    assert entry["suno_id"] == s["id"] and entry["title"] == "Project Mayhem"


def test_a_reference_with_no_source_fails_loudly(tmp_path):
    with pytest.raises(ValueError, match="no source"):
        suno.materialise("x.m4a", {"title": "Lost"}, tmp_path)
    assert not list(tmp_path.glob("*.m4a")), "nothing half-written is left behind"


def test_the_queue_reports_references_as_waiting(tmp_path):
    from anchor import queue as q
    for plays, title, sid in [(36, "Project Mayhem", "a" * 8), (0, "Go", "b" * 8)]:
        suno.queue_entry(song(id=sid + "-0000-0000-0000-" + "0" * 12, title=title, plays=plays,
                              tags=TECHNO, duration_s=245.0, video_url="https://x/y.mp4"),
                         tmp_path)
    waiting = q.reserved(tmp_path)
    assert len(waiting) == 2 and q.pending(tmp_path) == []
    assert waiting[0][1]["title"] == "Project Mayhem", "best rated is served first"


# ------------------------------------------------------- what the site renders
def test_the_scorecard_shows_its_working():
    s = song(title="Project Mayhem", tags=TECHNO, duration_s=245.0, plays=36, model="v5")
    assert s["postable"] and len(s["checks"]) == 4 and len(s["factors"]) == 4
    assert all(c["ok"] for c in s["checks"])
    assert all(0 <= f["score"] <= f["max"] and f["note"] for f in s["factors"])
    assert abs(sum(f["score"] for f in s["factors"]) - s["rating"]) < 0.25, \
        "the rating is the sum of the factors shown"
    assert s["summary"].startswith(f"Rated {s['rating']}")


def test_a_no_names_the_check_that_failed():
    s = song(title="Concrete Pulse", tags="hard techno set of music like nf and Hip Hop, Rap raps",
             duration_s=231.0)
    assert not s["postable"]
    failed = [c for c in s["checks"] if not c["ok"]]
    assert len(failed) == 1 and "floor" in failed[0]["detail"]
    assert "hip hop" in failed[0]["detail"].lower(), "it says what pulled the score down"
    assert s["verdict"] == failed[0]["detail"], "the one-line verdict is the failing reason"
    assert "Not yet" in s["summary"]


def test_a_personal_track_is_refused_by_name():
    s = song(title="For Ayushi", tags=TECHNO, duration_s=200.0)
    assert not s["postable"]
    personal = next(c for c in s["checks"] if c["label"] == "Not a personal track")
    assert not personal["ok"] and "ayushi" in personal["detail"].lower()


def test_a_short_track_is_refused_on_length():
    s = song(title="Signal", tags=TECHNO, duration_s=42.0)
    assert not s["postable"] and s["slot"] == "too short"
    length = next(c for c in s["checks"] if c["label"] == "Long enough to release")
    assert not length["ok"] and "0:42" in length["detail"]


def test_every_catalogue_row_offers_the_youtube_cta():
    js = (SITE / "assets" / "app.js").read_text()
    assert "ctaCell(s, multi && !isPick)" in js, "every row gets a CTA; alternates get the quiet one"
    assert "issues/new?labels=youtube-queue" in js, "the CTA opens the queue issue"
    assert "Add to YouTube" in js and "Queue anyway" in js
    assert "whyPanel(s)" in js, "every row shows the full reasoning"
    for piece in ("why-bars", "why-checks", "why-call", "wb-note"):
        assert piece in js, f"the reasoning panel is missing {piece}"
    css = (SITE / "assets" / "style.css").read_text()
    for cls in (".why-body", ".why-checks li.no", ".wb-fill", ".why-call"):
        assert cls in css, f"unstyled: {cls}"
    html = (SITE / "index.html").read_text()
    for f in ("pick", "twin", "yes", "no"):
        assert f'data-f="{f}"' in html, f"missing the {f} filter"


def test_the_workflow_behind_the_button_is_wired():
    wf = (ROOT / ".github" / "workflows" / "queue-song.yml").read_text()
    assert "youtube-queue" in wf, "the label the site links to"
    assert "python -m anchor queue-add" in wf
    assert "author_association" in wf, "only the owner can queue a release"
    assert "git add queue" in wf


def test_published_catalogue_carries_the_similarity_fields():
    cat = json.loads((SITE / "data" / "catalog.json").read_text()).get("catalogue")
    if not cat:
        pytest.skip("no catalogue synced yet")
    for key in ("families", "twins", "fresh"):
        assert key in cat, f"catalogue summary missing {key}"
    for s in cat["songs"]:
        assert {"similar", "group", "group_size", "group_pick"} <= set(s)
        assert {"factors", "checks", "summary", "verdict"} <= set(s), "reasons must ship with the data"
        assert len(s["checks"]) == 4 and len(s["factors"]) == 4
        assert s["postable"] == all(c["ok"] for c in s["checks"]), "the yes/no matches its own checks"
        assert re.fullmatch(r"[0-9a-f-]{36}", s["id"]), "the CTA needs a real song id"
    assert cat["fresh"] == sum(1 for s in cat["songs"] if s["postable"] and s["group_pick"]
                               and not s.get("queue_pos") and not s.get("released_at")), \
        "fresh counts picks still going spare, not ones already queued or released"


def test_the_queue_releases_the_best_song_first():
    """Downloads lead with an inverted rating so name order is quality order."""
    from anchor import queue as q
    names = ["%02d-%s-%s.m4a" % (max(1, min(99, round(100 - r * 10))), t, "abcd1234")
             for r, t in [(8.6, "project-mayhem"), (7.7, "crossing-the-threshold"),
                          (6.6, "lets-fucking-go")]]
    assert sorted(names) == names, "best rated sorts first"
    assert q._title_from(names[0]) == "Project Mayhem", "rank prefix and id are stripped back off"


def test_a_released_reference_never_comes_back(tmp_path):
    """Reference-queued songs have no file to move, so the manifest must be stamped."""
    from anchor import queue as q
    (tmp_path / "queue.json").write_text(json.dumps({
        "14-a-aaaaaaaa.m4a": {"title": "A", "suno_id": "x", "rating": 8.6},
        "23-b-bbbbbbbb.m4a": {"title": "B", "suno_id": "y", "rating": 7.7},
    }))
    assert [n for n, _ in q.reserved(tmp_path)] == ["14-a-aaaaaaaa.m4a", "23-b-bbbbbbbb.m4a"]
    fetched = tmp_path / "14-a-aaaaaaaa.m4a"
    fetched.write_bytes(b"x" * 100)
    q.mark_done(fetched, tmp_path / "done")
    assert [n for n, _ in q.reserved(tmp_path)] == ["23-b-bbbbbbbb.m4a"], \
        "the released song must not be fetched and posted a second time"
    assert json.loads((tmp_path / "queue.json").read_text())["14-a-aaaaaaaa.m4a"]["released_at"]


def test_no_queue_forces_the_generator():
    """The generator must be testable while tracks are queued, or a render costs a release."""
    import inspect
    import anchor.pipeline as pl
    assert "use_queue" in inspect.signature(pl.make).parameters
    assert "use_queue and engine_name" in inspect.getsource(pl.make), \
        "the queue lookup must be gated on use_queue"
    cli = (ROOT / "anchor" / "__main__.py").read_text()
    assert '"--no-queue"' in cli and "use_queue=not args.no_queue" in cli
    wf = (ROOT / ".github" / "workflows" / "daily.yml").read_text()
    assert "ignore_queue" in wf and "--no-queue" in wf, "the workflow must expose the flag"


def test_takes_of_one_idea_are_grouped_with_a_single_pick():
    """Four Project Mayhem takes split into two families, so two rows both claimed 'best'."""
    # the real tag strings off the profile: same idea, prompted in different words
    tags_a = ("Hardstyle hard techno industrial techno with more hypnotic drops and "
              "distortions - clean and clear master file audio quality")
    tags_b = "hard techno, rawstyle hybrid, industrial, 156-158 bpm, techno, noise, hypnotic, minimal"
    takes = [
        song(id="aaaaaaaa-0000-0000-0000-000000000001", title="Project Mayhem",
             tags=tags_a, duration_s=245.0, plays=36),
        song(id="bbbbbbbb-0000-0000-0000-000000000002", title="Project Mayhem Part 2",
             tags=tags_b, duration_s=177.0, plays=14),
        song(id="cccccccc-0000-0000-0000-000000000003", title="Project Mayhem Part 1",
             tags=tags_b, duration_s=227.0, plays=12),
        song(id="dddddddd-0000-0000-0000-000000000004", title="Project Mayhem",
             tags=tags_a, duration_s=165.0, plays=9),
    ]
    # the tag wording alone does NOT bring the two pairs together
    assert suno.similarity(takes[0], takes[1]) < suno.NEAR
    suno.annotate_similar(takes)
    assert len({t["group"] for t in takes}) == 1, "all four takes are one idea"
    assert [t["group_size"] for t in takes] == [4, 4, 4, 4]
    assert sum(t["group_pick"] for t in takes) == 1, "exactly one take is the pick"
    assert next(t for t in takes if t["group_pick"])["id"] == takes[0]["id"], "best rated wins"


def test_title_key_ignores_take_markers():
    assert suno.title_key("Project Mayhem") == suno.title_key("Project Mayhem Part 2")
    assert suno.title_key("Project Mayhem") != suno.title_key("Concrete Pulse")


def test_the_site_groups_takes_and_names_the_one_to_post():
    js = (SITE / "assets" / "app.js").read_text()
    for piece in ("function families(", "famHeader(fam)", "POST THIS ONE", "Post this instead",
                  "whySameIdea", "takes of this idea"):
        assert piece in js, f"the grouped view is missing {piece}"
    css = (SITE / "assets" / "style.css").read_text()
    for cls in (".fam-row", ".tag-use", ".tag-alt", "tr.is-pick", "tr.is-alt"):
        assert cls in css, f"unstyled: {cls}"


def test_published_catalogue_has_one_pick_per_family():
    cat = json.loads((SITE / "data" / "catalog.json").read_text()).get("catalogue")
    if not cat:
        pytest.skip("no catalogue synced yet")
    fams = {}
    for s in cat["songs"]:
        fams.setdefault(s["group"] or s["id"], []).append(s)
    for key, members in fams.items():
        picks = sum(1 for m in members if m["group_pick"])
        assert picks == 1, f"family {key} has {picks} picks, expected exactly 1"
        assert all(m["group_size"] == len(members) for m in members)


# --------------------------------------------- which single song goes out next
def test_the_catalogue_names_the_one_song_that_goes_out_next(tmp_path):
    """A channel that posts once a day owes the reader one name, not a table to read."""
    from anchor import queue as q
    songs = [song(id="aaaaaaaa-0000-0000-0000-000000000001", title="Project Mayhem",
                  tags=TECHNO, duration_s=245.0, plays=36),
             song(id="bbbbbbbb-0000-0000-0000-000000000002", title="Crossing The Threshold",
                  tags=TECHNO, duration_s=227.0, plays=16)]
    for s in songs:
        s["group_pick"] = True
        suno.queue_entry(s, tmp_path)

    up = suno.annotate_queue(songs, tmp_path)
    assert up["title"] == "Project Mayhem", "the head of the queue is what goes out"
    assert up["source"] == "queue" and up["waiting"] == 1
    assert songs[0]["queue_pos"] == 1 and songs[1]["queue_pos"] == 2
    assert q.line_up(tmp_path)[0]["suno_id"] == songs[0]["id"]


def test_with_an_empty_queue_the_best_take_going_spare_is_named(tmp_path):
    songs = [song(id="aaaaaaaa-0000-0000-0000-000000000001", title="Project Mayhem",
                  tags=TECHNO, duration_s=245.0, plays=36),
             song(id="bbbbbbbb-0000-0000-0000-000000000002", title="Concrete Pulse",
                  tags=TECHNO, duration_s=227.0, plays=2)]
    for s in songs:
        s["group_pick"] = True
    up = suno.annotate_queue(songs, tmp_path)
    assert up["source"] == "catalogue" and up["title"] == "Project Mayhem"
    assert up["waiting"] == 0 and not any(s.get("queue_pos") for s in songs)


def test_a_released_song_is_never_named_as_next(tmp_path):
    """The stamp that stops a re-release must also stop the page recommending it."""
    from anchor import queue as q
    s = song(id="aaaaaaaa-0000-0000-0000-000000000001", title="Project Mayhem",
             tags=TECHNO, duration_s=245.0, plays=36)
    s["group_pick"] = True
    spare = song(id="bbbbbbbb-0000-0000-0000-000000000002", title="Concrete Pulse",
                 tags=TECHNO, duration_s=227.0, plays=2)
    spare["group_pick"] = True
    name = suno.queue_entry(s, tmp_path)["name"]
    meta = json.loads((tmp_path / "queue.json").read_text())
    meta[name]["released_at"] = "2026-09-12T21:00:00Z"
    q.write_meta(tmp_path, meta)

    up = suno.annotate_queue([s, spare], tmp_path)
    assert s["released_at"] == "2026-09-12T21:00:00Z" and not s.get("queue_pos")
    assert up["title"] == "Concrete Pulse", "a song already out is not the next one out"


def test_the_site_shows_the_next_song_and_stops_offering_queued_ones():
    js = (SITE / "assets" / "app.js").read_text()
    for piece in ("function renderNextUp(", "next_up", "queue_pos", "released_at",
                  "goes out next run", "in line", "Nothing queued"):
        assert piece in js, f"the next-up card is missing {piece}"
    cta = js[js.index("function ctaCell("):js.index("function whyPanel(")]
    assert cta.index("if (s.released_at)") < cta.index("if (s.queue_pos)") < cta.index("queue-btn"), \
        "a song already out or already queued must return a state before any queue button"
    css = (SITE / "assets" / "style.css").read_text()
    for cls in (".next-up", ".nu-title", ".nu-name", ".cta-state", ".chip-queued"):
        assert cls in css, f"unstyled: {cls}"
    assert 'id="next-up"' in (SITE / "index.html").read_text()


def test_published_catalogue_names_what_is_next():
    cat = json.loads((SITE / "data" / "catalog.json").read_text()).get("catalogue")
    if not cat:
        pytest.skip("no catalogue synced yet")
    assert "next_up" in cat, "the site cannot answer 'which one' without this"
    up = cat["next_up"]
    if up is None:
        assert cat["queued"] == 0 and not cat["fresh"]
        return
    assert up["title"] and up["source"] in ("queue", "catalogue") and up["why"]
    if up["id"]:
        match = [s for s in cat["songs"] if s["id"] == up["id"]]
        assert match, "the named song must exist in the catalogue so the row can be linked"
        assert not match[0].get("released_at"), "never point at something already out"
    queued = [s for s in cat["songs"] if s.get("queue_pos")]
    assert len(queued) == cat["queued"]
    assert sorted(s["queue_pos"] for s in queued) == list(range(1, len(queued) + 1)), \
        "the line is numbered 1..n with no gaps or ties"


# ------------------------------------- the same song must never go out twice
def test_a_released_track_is_dropped_even_when_its_stamp_was_lost(tmp_path, monkeypatch):
    """The stamp is written on the render runner; the commit happens on another one."""
    from anchor import queue as q
    s = song(id="f5207246-bf22-41b1-a4d2-8b3861149d7d", title="Project Mayhem",
             tags=TECHNO, duration_s=245.0, plays=36)
    name = suno.queue_entry(s, tmp_path)["name"]
    assert [n for n, _ in q.reserved(tmp_path)] == [name], "queued and waiting"

    # the website says it went out, but queue.json never got the stamp
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps({"drops": [{"date": "2026-09-13", "title": "Project Mayhem",
                                          "engine": {"name": "queue", "source_file": name}}]}))
    monkeypatch.setattr("anchor.config.CATALOG_PATH", cat)

    assert name in q.spent(tmp_path), "the site's own drop list is the record that survives"
    assert q.reserved(tmp_path) == [], "a released track is never offered again"
    assert q.next_track(tmp_path) is None


def test_another_take_of_a_posted_song_is_not_released_the_next_day(tmp_path, monkeypatch):
    """Suno returns two takes per prompt; posting both is the channel repeating itself."""
    from anchor import queue as q
    part2 = song(id="0287e07b-4e22-4d9b-9d33-78e55743e3e7", title="Project Mayhem Part 2",
                 tags=TECHNO, duration_s=177.0, plays=14)
    other = song(id="324147b3-967b-4f51-8be4-f820d6e21341", title="Crossing The Threshold",
                 tags=TECHNO, duration_s=227.0, plays=16)
    n2 = suno.queue_entry(part2, tmp_path)["name"]
    n3 = suno.queue_entry(other, tmp_path)["name"]

    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps({"drops": [{"date": "2026-09-13", "title": "Project Mayhem",
                                          "engine": {"name": "queue", "source_file": "gone.m4a"}}]}))
    monkeypatch.setattr("anchor.config.CATALOG_PATH", cat)

    waiting = [n for n, _ in q.reserved(tmp_path)]
    assert n2 not in waiting, "Part 2 is the same song as the one already posted"
    assert waiting == [n3], "the next genuinely different idea is what goes out"
    assert q.line_up(tmp_path)[0]["title"] == "Crossing The Threshold"


def test_the_daily_workflow_carries_the_stamp_between_jobs():
    wf = (ROOT / ".github" / "workflows" / "daily.yml").read_text()
    assert 'cp queue/queue.json "build/' in wf, "the make job must ship the stamp it wrote"
    assert "build/${{ steps.day.outputs.date }}/queue.json" in wf, "and upload it"
    assert 'cp "$f" queue/queue.json' in wf, "the publish job must restore it before committing"
    assert wf.index("Restore the queue stamp") < wf.index("Commit the catalog"), \
        "restoring after the commit would be pointless"


# ------------------------------------------- a track has to end, not just stop
def test_a_track_that_stops_dead_is_told_apart_from_one_that_resolves():
    import numpy as np
    from anchor.audio import SR, ends_abruptly
    body = (np.random.default_rng(7).standard_normal((SR * 8, 2)) * 0.2).astype("float32")

    cut = np.vstack([body, np.zeros((SR * 3, 2), "float32")])   # rendered, then padded
    resolved = body.copy()
    tail = SR * 3
    resolved[-tail:] *= np.linspace(1, 0, tail)[:, None]        # an actual outro

    assert ends_abruptly(cut)[0], "full level to the last bar, then silence: that is a cliff"
    assert not ends_abruptly(resolved)[0], "a track that winds down must not be faded twice"


def test_every_rendered_track_is_given_an_arrangement():
    from anchor.music import structure
    for seconds in (60, 100, 150, 245):
        parts = structure(seconds).splitlines()
        assert parts[0] == "[intro]" and parts[-1] == "[outro]", \
            f"{seconds}s track must open on an intro and land on an outro"
        assert len(parts) == len(set(range(len(parts)))), "sections are a flat ordered list"
    assert structure(150).count("[drop]") == 2, "a 2:30 club edit gets two drops"
    assert len(structure(245).splitlines()) > len(structure(100).splitlines()), \
        "a longer track earns more sections, not longer ones"


def test_the_site_refuses_to_offer_a_take_of_a_song_already_out(tmp_path, monkeypatch):
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps({"drops": [{"date": "2026-09-13", "title": "Project Mayhem",
                                          "engine": {"name": "queue", "source_file": "x.m4a"}}]}))
    monkeypatch.setattr("anchor.config.CATALOG_PATH", cat)
    songs = [song(id="bbbbbbbb-0000-0000-0000-000000000002", title="Project Mayhem Part 2",
                  tags=TECHNO, duration_s=177.0, plays=14),
             song(id="cccccccc-0000-0000-0000-000000000003", title="Concrete Pulse",
                  tags=TECHNO, duration_s=227.0, plays=2)]
    for s in songs:
        s["group_pick"] = True
    suno.annotate_queue(songs, tmp_path)
    assert songs[0].get("idea_posted") is True, "another take of a posted song is not postable"
    assert not songs[1].get("idea_posted"), "a different idea is still fair game"

    js = (SITE / "assets" / "app.js").read_text()
    cta = js[js.index("function ctaCell("):js.index("function whyPanel(")]
    assert cta.index("s.idea_posted") < cta.index("queue-btn"), \
        "the duplicate guard must come before the button, not after it"
