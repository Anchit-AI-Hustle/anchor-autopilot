"""Several songs a day (Anchit, 2026-10-24): drop ids YYYY-MM-DD, -2 ... -5, each its own
record, name, lane, seed and post time, as many as the YouTube quota allows. Nothing here
touches the network."""
import subprocess
from datetime import date, timedelta
from pathlib import Path

import re
import textwrap

import pytest

from anchor import catalog
from anchor.brief import make_brief, post_time
from anchor.config import load_profile
from anchor.pipeline import is_release_day
from anchor.util import split_drop_id

ROOT = Path(__file__).resolve().parent.parent


def test_drop_ids():
    assert split_drop_id("2026-10-25") == ("2026-10-25", 1)
    assert split_drop_id("2026-10-25-2") == ("2026-10-25", 2)
    for bad in ("2026-10-25-1", "2026-10-25-10", "2026-10-25b", "25-10-2026", "", None):
        with pytest.raises(ValueError):
            split_drop_id(bad)


def test_each_slot_has_its_own_post_time():
    p = load_profile()
    assert p.schedule["post_time_utc"] == "17:30"
    assert p.schedule["extra_post_times_utc"] == ["19:30", "21:30", "23:00", "23:45"]
    times = [post_time(p, "2026-10-25" + ("" if n == 1 else f"-{n}")).strftime("%H:%M") for n in range(1, 6)]
    assert times == ["17:30", "19:30", "21:30", "23:00", "23:45"]
    assert post_time(p, "2026-10-25", 2).strftime("%H:%M") == "19:30"
    assert post_time(p, "2026-10-25-9").strftime("%H:%M") == "23:45", "a slot past the list keeps the last time"


def test_the_first_song_of_a_day_is_unchanged():
    p = load_profile()
    b = make_brief(p, "2026-10-25", [])
    assert b["id"] == b["date"] == "2026-10-25" and b["slot"] == 1 and b["post_at"] == "2026-10-25T17:30:00Z"


def test_the_second_song_is_a_different_record_the_same_day():
    p = load_profile()
    first = make_brief(p, "2026-10-25", [])
    hist = [{"id": first["id"], "date": first["date"], "title": first["title"], "lane": first["lane"],
             "family": first["family"], "key": first["key"]}]
    second = make_brief(p, "2026-10-25-2", hist)
    assert second["id"] == "2026-10-25-2" and second["date"] == "2026-10-25" and second["slot"] == 2
    assert second["post_at"] == "2026-10-25T19:30:00Z"
    assert second["title"] != first["title"] and second["seed"] != first["seed"]
    assert second["lane"] != first["lane"], "never the same genre twice in a row, even within a day"
    assert second["family"] != first["family"] and second["key"] != first["key"]


def test_sixty_days_of_five_songs_never_repeat_a_title_or_a_genre_back_to_back():
    p = load_profile()
    hist, titles = [], []
    start = date(2026, 10, 25)
    for i in range(60):
        day = (start + timedelta(days=i)).isoformat()
        for drop_id in (day, *(f"{day}-{n}" for n in range(2, 6))):
            b = make_brief(p, drop_id, hist)
            if hist:
                assert b["lane"] != hist[0]["lane"], drop_id
            hist.insert(0, {"id": b["id"], "date": b["date"], "title": b["title"], "lane": b["lane"],
                            "family": b["family"], "key": b["key"]})
            titles.append(b["title"])
    assert len(titles) == len(set(t.lower() for t in titles)) == 300
    assert {h["lane"] for h in hist} == {l.id for l in p.active_lanes}


def test_catalogue_orders_the_second_song_after_the_first():
    cat = {"drops": []}
    for d in ({"id": "2026-10-24", "date": "2026-10-24"}, {"id": "2026-10-25-2", "date": "2026-10-25"},
              {"id": "2026-10-25", "date": "2026-10-25"}):
        catalog.upsert(cat, {**d, "title": d["id"]})
    assert [d["id"] for d in catalog.history(cat)] == ["2026-10-25-2", "2026-10-25", "2026-10-24"]
    assert [d["id"] for d in cat["drops"]] == ["2026-10-25-2", "2026-10-25", "2026-10-24"]


def test_cadence_reads_a_drop_id(monkeypatch):
    p = load_profile()
    assert is_release_day(p, "2026-10-25-2")
    monkeypatch.setitem(p.schedule, "every_days", 2)
    assert is_release_day(p, "2026-10-26-2") == is_release_day(p, "2026-10-26")


WORKFLOW = (ROOT / ".github" / "workflows" / "daily.yml").read_text()


def test_one_run_a_day_after_the_quota_reset_and_a_backup_that_fills_gaps():
    head = WORKFLOW.split("workflow_dispatch:", 1)[0]
    crons = re.findall(r'- cron: "([^"]+)"', head)
    assert crons == ["37 8 * * *", "37 13 * * *"]
    assert all(int(c.split()[1]) >= 8 for c in crons), "after the Pacific quota reset all year (08:00 UTC in winter)"
    assert "group: daily-drop\n  cancel-in-progress: false" in WORKFLOW, "the runs go one after the other"
    for other in ("fullvideos.yml", "uploads.yml"):
        text = (ROOT / ".github" / "workflows" / other).read_text()
        hour = int(re.search(r'- cron: "\d+ (\d+) ', text).group(1))
        assert hour < 7, f"{other} runs before the day's drops, so a pending drop never cancels it"


def test_the_songs_render_side_by_side():
    make = WORKFLOW.split("\n  make:\n", 1)[1].split("\n  pages:\n", 1)[0]
    assert "fail-fast: false" in make and "drop: ${{ fromJSON(needs.plan.outputs.drops) }}" in make
    assert "anchor reserve --plan" in make, "each runner holds the earlier songs' briefs"
    pages = WORKFLOW.split("\n  pages:\n", 1)[1].split("\n  publish:\n", 1)[0]
    publish = WORKFLOW.split("\n  publish:\n", 1)[1].split("\n  report-failure:\n", 1)[0]
    for job in (pages, publish):
        assert "!cancelled()" in job and "pattern: drop-*" in job, "the songs that made it go out even if one failed"
    assert publish.index("anchor has-drop") < publish.index("anchor quota-ok") < publish.index("anchor publish"), \
        "a re-run never posts a song twice, and the quota is checked before every song"
    assert make.index("Publish the release files") < make.index("Upload drop files"), \
        "a song reaches YouTube only after its release page exists"
    commit = publish.split("- name: Commit the catalog", 1)[1]
    assert "if: ${{ !cancelled() }}" in commit, "songs already posted are recorded even if a later one fails"


def _plan_step() -> str:
    block = WORKFLOW.split("id: plan\n", 1)[1].split("\n  make:", 1)[0].split("\n      - name:", 1)[0]
    return textwrap.dedent(block.split("run: |\n", 1)[1])


@pytest.mark.parametrize("date_input,planned,want", [
    ("", '["2026-10-25", "2026-10-25-2", "2026-10-25-3"]', ["2026-10-25", "2026-10-25-2", "2026-10-25-3"]),
    ("", "[]", []),
    ("2026-10-25-2", "ignored", ["2026-10-25-2"]),
])
def test_the_plan_step_lists_the_drops(tmp_path, date_input, planned, want):
    """Run the workflow's own plan shell with a stand-in for `python -m anchor plan-drops`."""
    import json
    import sys
    shim = tmp_path / "python"
    shim.write_text(f"#!/bin/sh\nif [ \"$1\" = \"-m\" ]; then echo 'why' >&2; echo '{planned}'; else exec {sys.executable} \"$@\"; fi\n")
    shim.chmod(0o755)
    out_file = tmp_path / "out"
    script = _plan_step().replace("${{ inputs.date }}", date_input)
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "GITHUB_OUTPUT": str(out_file)}
    subprocess.run(["bash", "-e", "-c", script], capture_output=True, text=True, check=True, cwd=tmp_path, env=env)
    lines = dict(l.split("=", 1) for l in out_file.read_text().splitlines())
    assert json.loads(lines["drops"]) == want and lines["count"] == str(len(want))
    for d in want:
        split_drop_id(d)
