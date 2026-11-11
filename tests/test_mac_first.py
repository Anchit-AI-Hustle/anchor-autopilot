"""Mac first (Anchit, 2026-11-11: better songs from now on): a scheduled run that finds the Mac
asleep waits for a later run instead of handing the day to the small CPU model; the last run of
the day still renders on the CPU, and a run he starts by hand is never held."""
import os
import subprocess
from pathlib import Path

import re
import textwrap

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "daily.yml"


def where_script() -> str:
    text = WF.read_text()
    block = text.split("        id: where\n", 1)[1].split("        run: |\n", 1)[1]
    lines = []
    for line in block.splitlines():
        if line.strip() and not line.startswith("          "):
            break
        lines.append(line)
    return textwrap.dedent("\n".join(lines))


def pick(tmp_path, *, age, event, hour, want="auto"):
    out = tmp_path / "out.txt"
    out.write_text("")
    import time
    seen = str(int(time.time()) - age)
    # a fake date that answers the hour asked and the real epoch for %s
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "date").write_text(f'#!/bin/bash\nif [ "$2" = "+%H" ]; then echo {hour:02d}; else /bin/date "$@"; fi\n')
    (bindir / "date").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "SEEN": seen, "WANT": want,
           "EVENT": event, "GITHUB_OUTPUT": str(out)}
    subprocess.run(["bash", "-e", "-c", where_script()], env=env, check=True, capture_output=True)
    return dict(line.split("=", 1) for line in out.read_text().splitlines())["renderer"]


def test_the_mac_awake_renders_on_the_mac(tmp_path):
    assert pick(tmp_path, age=60, event="schedule", hour=8) == "mac"


def test_a_scheduled_run_waits_for_the_mac_before_19_utc(tmp_path):
    assert pick(tmp_path, age=3 * 3600, event="schedule", hour=16) == "wait"


def test_the_last_run_of_the_day_falls_back_to_the_cpu(tmp_path):
    assert pick(tmp_path, age=3 * 3600, event="schedule", hour=19) == "cpu"


def test_a_run_started_by_hand_is_never_held(tmp_path):
    assert pick(tmp_path, age=3 * 3600, event="workflow_dispatch", hour=9) == "cpu"
    assert pick(tmp_path, age=3 * 3600, event="schedule", hour=9, want="cpu") == "cpu"


def test_a_waiting_run_plans_no_songs():
    text = WF.read_text()
    assert re.search(r"count: \$\{\{ steps\.where\.outputs\.renderer == 'wait' && '0'", text)
    assert '- cron: "37 19 * * *"' in text
