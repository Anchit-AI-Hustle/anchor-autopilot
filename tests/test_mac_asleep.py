"""A Mac that falls asleep never costs a song (Anchit, 2026-11-21: "ensure Mac being asleep is not
a problem"): the heartbeat stamps a file a running workflow can read, and the daily run stops a
run whose Mac fell asleep mid-song so the next scheduled run renders on GitHub's CPU."""
import os
import subprocess
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows" / "daily.yml"


def watchdog_script() -> str:
    text = WF.read_text()
    job = text.split("  mac-alive:\n", 1)[1]
    block = job.split("        run: |\n", 1)[1]
    lines = []
    for line in block.splitlines():
        if line.strip() and not line.startswith("          "):
            break
        lines.append(line)
    return textwrap.dedent("\n".join(lines))


def run_watchdog(tmp_path, *, alive_age_s, left="1"):
    """The watchdog against a fake gh: songs still rendering, the Mac's stamp alive_age_s old."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stamp = (datetime.now(timezone.utc) - timedelta(seconds=alive_age_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
    log = tmp_path / "gh.log"
    (bindir / "gh").write_text(f"""#!/bin/bash
echo "$@" >> {log}
case "$*" in
  *"/jobs"*) echo {left} ;;
  *"releases/tags/mac-alive"*) echo {stamp} ;;
  "run cancel"*) exit 0 ;;
esac
""")
    (bindir / "gh").chmod(0o755)
    (bindir / "sleep").write_text("#!/bin/bash\nexit 0\n")
    (bindir / "sleep").chmod(0o755)
    script = watchdog_script().replace("seq 1 240", "seq 1 5")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_REPO": "o/r", "RUN_ID": "42", "GH_TOKEN": "x"}
    r = subprocess.run(["bash", "-e", "-c", script], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return log.read_text() if log.exists() else "", r.stdout


def test_a_mac_asleep_mid_song_stops_the_run(tmp_path):
    calls, out = run_watchdog(tmp_path, alive_age_s=40 * 60)
    assert "run cancel 42" in calls and "fell asleep" in out


def test_an_awake_mac_is_left_to_finish(tmp_path):
    calls, _ = run_watchdog(tmp_path, alive_age_s=60)
    assert "run cancel" not in calls


def test_a_finished_run_ends_the_watch(tmp_path):
    calls, out = run_watchdog(tmp_path, alive_age_s=40 * 60, left="0")
    assert "run cancel" not in calls and "Every song is rendered" in out


def test_the_watchdog_runs_only_beside_mac_renders():
    text = WF.read_text()
    job = text.split("  mac-alive:\n", 1)[1].split("\n  make:\n", 1)[0]
    assert "needs.plan.outputs.renderer == 'mac'" in job and "runs-on: ubuntu-24.04" in job
    assert "timeout-minutes: 485" in job


def test_the_heartbeat_stamps_where_a_run_can_read_it():
    setup = (ROOT / "scripts" / "mac-runner-setup.sh").read_text()
    hb = setup.split("<<HBEOF\n", 1)[1].split("\nHBEOF", 1)[0]
    assert "gh release upload mac-alive" in hb and "alive.txt" in hb and "--clobber" in hb
    assert "gh release create mac-alive" in hb and "--prerelease" in hb
