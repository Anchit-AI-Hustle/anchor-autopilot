"""Every new song goes up as soon as it is made (Anchit, 2026-11-14: "ensure all new songs are
uploaded as soon as they are created"). GitHub starts scheduled runs hours late, so the Mac's
heartbeat starts a posting run itself (tools/mac-autostart.sh), and a posting run first posts any
song an earlier run made but did not post."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "mac-autostart.sh"
NOW = "2026-11-14T10:00:00Z"


def _run(tmp_path, *, runs, plan='["2026-11-14-2"]', hm="1031", count=None, off=False, listener=True):
    base = tmp_path / "gpu"
    (base / "runner-venv" / "bin").mkdir(parents=True, exist_ok=True)
    (base / "autostart-repo" / ".git").mkdir(parents=True, exist_ok=True)
    bins = tmp_path / "bin"
    bins.mkdir(exist_ok=True)
    py = base / "runner-venv" / "bin" / "python"
    py.write_text(f"#!/bin/sh\nif [ \"$1\" = \"-m\" ]; then echo 'why: 1700 of 8000' >&2; echo '{plan}'; "
                  f"else exec {sys.executable} \"$@\"; fi\n")
    (bins / "gh").write_text("#!/bin/sh\nif [ \"$1\" = run ]; then cat \"$RUNS_FILE\"; "
                             "elif [ \"$1\" = workflow ]; then echo \"$@\" >> \"$DISPATCHED\"; fi\n")
    (bins / "git").write_text("#!/bin/sh\nexit 0\n")
    (bins / "pgrep").write_text(f"#!/bin/sh\nexit {0 if listener else 1}\n")
    for f in ("gh", "git", "pgrep"):
        (bins / f).chmod(0o755)
    py.chmod(0o755)
    (tmp_path / "runs.json").write_text(json.dumps(runs))
    if count is not None:
        (base / "autostart-2026-11-14.count").write_text(str(count))
    if off:
        (base / "autostart.off").write_text("")
    disp = tmp_path / "dispatched"
    env = {"ANCHOR_GPU_DIR": str(base), "ANCHOR_PATH_PREFIX": str(bins), "ANCHOR_NOW_HM": hm,
           "ANCHOR_TODAY": "2026-11-14", "RUNS_FILE": str(tmp_path / "runs.json"),
           "DISPATCHED": str(disp), "HOME": str(tmp_path)}
    subprocess.run(["bash", str(SCRIPT)], env=env, check=True, capture_output=True, text=True)
    return disp.read_text() if disp.exists() else ""


OLD = [{"status": "completed", "createdAt": "2026-11-14T09:27:56Z"}]


def test_starts_a_posting_run_on_the_mac_when_songs_are_due(tmp_path):
    out = _run(tmp_path, runs=OLD)
    assert "workflow run daily.yml" in out and "renderer=mac" in out
    assert "dry_run" not in out and "date=" not in out, "a posting run that plans the day itself"
    assert (tmp_path / "gpu" / "autostart-2026-11-14.count").read_text().strip() == "1"


@pytest.mark.parametrize("kw", [
    {"runs": [{"status": "in_progress", "createdAt": "2026-11-14T09:27:56Z"}]},  # one at a time
    {"runs": [{"status": "queued", "createdAt": "2026-11-14T09:27:56Z"}]},
    {"runs": OLD, "plan": "[]"},          # nothing due or no quota left
    {"runs": OLD, "hm": "0700"},          # before the quota reset: overnight batch owns the Mac
    {"runs": OLD, "hm": "2130"},          # the overnight render-only batch is about to start
    {"runs": OLD, "count": 8},            # at most 8 starts a day
    {"runs": OLD, "off": True},           # paused by hand
    {"runs": OLD, "listener": False},     # the runner is not up
])
def test_does_not_start_a_run(tmp_path, kw):
    assert _run(tmp_path, **kw) == ""


def test_waits_45_minutes_after_the_last_run(tmp_path):
    import datetime as d
    recent = (d.datetime.now(d.timezone.utc) - d.timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _run(tmp_path, runs=[{"status": "completed", "createdAt": recent}]) == ""


def test_the_heartbeat_runs_the_autostart():
    setup = (ROOT / "scripts" / "mac-runner-setup.sh").read_text()
    assert "mac-autostart.sh" in setup and "autostart-repo" in setup


def test_a_posting_run_first_posts_songs_already_made():
    wf = (ROOT / ".github" / "workflows" / "daily.yml").read_text()
    plan = wf.split("id: plan\n", 1)[1].split("- name: Pick where the songs render", 1)[0]
    assert '[ -z "${{ inputs.date }}" ] && [ -z "$FROM" ]' in plan
    assert '"${{ inputs.dry_run }}" != "true"' in plan, "a render-only run never posts"
    assert "python -m anchor has-drop --date" in plan, "a song already out is never posted again"


@pytest.mark.parametrize("posted,want_from", [("no", "555"), ("yes", "")])
def test_a_made_song_not_yet_up_is_posted_by_the_next_run(tmp_path, posted, want_from):
    """Run the workflow's own plan shell: an earlier run made today's -3, so the next posting run
    posts it from that run instead of making it again, unless it is already on YouTube."""
    import datetime as d
    import shutil
    import textwrap
    wf = (ROOT / ".github" / "workflows" / "daily.yml").read_text()
    block = wf.split("id: plan\n", 1)[1].split("\n      - name:", 1)[0]
    script = textwrap.dedent(block.split("run: |\n", 1)[1])
    script = (script.replace("${{ inputs.date }}", "").replace("${{ inputs.from_run }}", "")
              .replace("${{ github.event_name }}", "workflow_dispatch").replace("${{ inputs.dry_run }}", "false"))
    today = d.datetime.now(d.timezone.utc).strftime("%Y-%m-%d")
    (tmp_path / "python").write_text(
        "#!/bin/sh\nif [ \"$1 $3\" = \"-m plan-drops\" ]; then echo why >&2; "
        f"echo '[\"{today}-2\", \"{today}-3\"]'; elif [ \"$1 $3\" = \"-m has-drop\" ]; then echo {posted}; "
        f"else exec {sys.executable} \"$@\"; fi\n")
    (tmp_path / "gh").write_text(
        "#!/bin/sh\ncase \"$2\" in *artifacts*) echo drop-" + today + "-3; echo drop-" + today
        + "-3-video;; *runs*) echo 555;; esac\n")
    if shutil.which("gdate"):
        (tmp_path / "date").write_text(f"#!/bin/sh\nexec {shutil.which('gdate')} \"$@\"\n")
    for f in ("python", "gh", "date"):
        if (tmp_path / f).exists():
            (tmp_path / f).chmod(0o755)
    out = tmp_path / "out"
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "GITHUB_OUTPUT": str(out), "GITHUB_REPOSITORY": "o/r"}
    subprocess.run(["bash", "-e", "-c", script], check=True, capture_output=True, text=True, cwd=tmp_path, env=env)
    lines = dict(l.split("=", 1) for l in out.read_text().splitlines())
    assert lines["from_run"] == want_from
    if want_from:
        assert json.loads(lines["drops"]) == [f"{today}-3"], "only the made song, nothing made again"
