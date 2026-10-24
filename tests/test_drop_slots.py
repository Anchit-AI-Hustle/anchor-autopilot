"""Two songs a day (Anchit, 2026-10-24): drop ids YYYY-MM-DD and YYYY-MM-DD-2, each its own
record, name, lane, seed and post time. Nothing here touches the network."""
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
    assert p.schedule["post_time_utc"] == "17:30" and p.schedule["extra_post_times_utc"] == ["21:30"]
    assert post_time(p, "2026-10-25").strftime("%H:%M") == "17:30"
    assert post_time(p, "2026-10-25", 2).strftime("%H:%M") == "21:30"
    assert post_time(p, "2026-10-25-2").strftime("%H:%M") == "21:30"
    assert post_time(p, "2026-10-25-3").strftime("%H:%M") == "21:30", "a slot past the list keeps the last time"


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
    assert second["post_at"] == "2026-10-25T21:30:00Z"
    assert second["title"] != first["title"] and second["seed"] != first["seed"]
    assert second["lane"] != first["lane"], "never the same genre twice in a row, even within a day"
    assert second["family"] != first["family"] and second["key"] != first["key"]


def test_sixty_days_of_two_songs_never_repeat_a_title_or_a_genre_back_to_back():
    p = load_profile()
    hist, titles = [], []
    start = date(2026, 10, 25)
    for i in range(60):
        day = (start + timedelta(days=i)).isoformat()
        for drop_id in (day, f"{day}-2"):
            b = make_brief(p, drop_id, hist)
            if hist:
                assert b["lane"] != hist[0]["lane"], drop_id
            hist.insert(0, {"id": b["id"], "date": b["date"], "title": b["title"], "lane": b["lane"],
                            "family": b["family"], "key": b["key"]})
            titles.append(b["title"])
    assert len(titles) == len(set(t.lower() for t in titles)) == 120
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


def _pick_step() -> str:
    """The shell of the "Pick the drop date" step (id: day), dedented."""
    block = WORKFLOW.split("id: day\n", 1)[1].split("\n      - name:", 1)[0]
    return textwrap.dedent(block.split("run: |\n", 1)[1])


def test_two_schedules_and_the_second_makes_slot_two():
    head = WORKFLOW.split("workflow_dispatch:", 1)[0]
    assert re.findall(r'- cron: "([^"]+)"', head) == ["7 7 * * *", "7 11 * * *"]
    assert "group: daily-drop\n  cancel-in-progress: false" in WORKFLOW, "the two runs go one after the other"


@pytest.mark.parametrize("schedule,date_input,want", [
    ("7 7 * * *", "", "{today}"),
    ("7 11 * * *", "", "{today}-2"),
    ("", "2026-10-25-2", "2026-10-25-2"),
    ("", "2026-10-25", "2026-10-25"),
])
def test_the_pick_step_names_the_drop(tmp_path, schedule, date_input, want):
    """Run the workflow's own shell for the date line, with GitHub's expressions filled in."""
    run = _pick_step()
    head = run.split("echo \"date=$DATE\"")[0]
    script = (head.replace("${{ inputs.date }}", date_input)
                  .replace("${{ github.event.schedule }}", schedule)) + 'echo "$DATE"\n'
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout.strip()
    today = subprocess.run(["date", "-u", "+%F"], capture_output=True, text=True).stdout.strip()
    assert out == want.format(today=today)
    split_drop_id(out)
