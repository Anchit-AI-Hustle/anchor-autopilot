"""The Drop run's catalogue commit when main moved during the render (2026-10-24-3: a 4.5 h
render, the previous drop committed meanwhile, the rebase hit conflicts and the live song never
reached the catalogue). Runs the workflow's own shell against a real local git origin."""
import re
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github" / "workflows" / "daily.yml").read_text()


def _step(name: str) -> str:
    block = WORKFLOW.split(f"- name: {name}\n", 1)[1].split("\n      - name:", 1)[0]
    return textwrap.dedent(block.split("run: |\n", 1)[1])


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def test_every_job_checks_out_the_branch_as_it_is_now():
    assert WORKFLOW.count("uses: actions/checkout@v4") == 4
    assert WORKFLOW.count("uses: actions/checkout@v4\n        with:\n          ref: ${{ github.ref }}") == 4


def test_a_moved_main_is_recorded_on_top_not_merged(tmp_path):
    origin, work, other = tmp_path / "origin.git", tmp_path / "work", tmp_path / "other"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(work))
    for d in (work,):
        git(d, "config", "user.name", "t"); git(d, "config", "user.email", "t@t")
    (work / "site" / "data").mkdir(parents=True)
    (work / "site" / "covers").mkdir()
    (work / "queue").mkdir()
    (work / "site" / "og.jpg").write_bytes(b"og0")
    (work / "site" / "data" / "catalog.json").write_text('["2026-10-24"]\n')
    git(work, "add", "."); git(work, "commit", "-q", "-m", "base"); git(work, "push", "-q", "origin", "main")

    # another drop lands on main while this one renders
    git(tmp_path, "clone", "-q", str(origin), str(other))
    git(other, "config", "user.name", "o"); git(other, "config", "user.email", "o@o")
    (other / "site" / "data" / "catalog.json").write_text('["2026-10-24-2", "2026-10-24"]\n')
    (other / "site" / "og.jpg").write_bytes(b"og-2")
    git(other, "commit", "-qam", "drop -2"); git(other, "push", "-q", "origin", "main")

    # this run's record step, on its stale checkout: conflicts with -2 on every file
    (work / "site" / "data" / "catalog.json").write_text('["2026-10-24-3", "2026-10-24"]\n')
    (work / "site" / "og.jpg").write_bytes(b"og-3")
    (work / "build" / "2026-10-24-3").mkdir(parents=True)
    (work / "build" / "2026-10-24-3" / "meta.json").write_text(
        '{"brief": {"title": "Compress Vector"}, "files": {"full_916": "x-full-916.mp4"}}')
    (work / "published.txt").write_text("2026-10-24-3\n")
    (work / ".git" / "info" / "exclude").write_text("build/\npublished.txt\n")

    # stand-in for `python -m anchor record`: an upsert of this drop into whatever catalogue is there
    bin_dir = tmp_path / "bin"; bin_dir.mkdir()
    (bin_dir / "python").write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import json, os, sys
        if sys.argv[1:3] != ["-m", "anchor"]:
            os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])
        if sys.argv[3] == "queue-stamp":
            sys.exit(0)
        assert sys.argv[3] == "record", sys.argv
        p = "site/data/catalog.json"
        c = json.load(open(p))
        c = ["2026-10-24-3"] + [d for d in c if d != "2026-10-24-3"]
        open(p, "w").write(json.dumps(c) + "\\n")
        open("site/og.jpg", "wb").write(b"og-3")
        """))
    (bin_dir / "python").chmod(0o755)
    (bin_dir / "sleep").write_text("#!/bin/sh\nexit 0\n"); (bin_dir / "sleep").chmod(0o755)

    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "MADE": "2026-10-24-3",
           "ROBOT_NAME": "r", "ROBOT_EMAIL": "r@r", "GITHUB_REF_NAME": "main", "GITHUB_REPOSITORY": "o/r",
           "PAGE_URL": "https://p/", "RUN_URL": "https://run"}
    res = subprocess.run(["bash", "-e", "-c", _step("Commit the catalog (triggers the website deploy)")],
                         cwd=work, env=env, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "recording the songs again" in res.stdout

    git(other, "pull", "-q")
    assert (other / "site" / "data" / "catalog.json").read_text() == '["2026-10-24-3", "2026-10-24-2", "2026-10-24"]\n'
    log = git(other, "log", "--format=%s")
    assert log.splitlines()[:2] == ["drop: 2026-10-24-3 · Compress Vector", "drop -2"], "one clean commit on top"
    assert not re.search(r"<<<<<<<|>>>>>>>", (other / "site" / "data" / "catalog.json").read_text())


def test_the_recovery_workflow_never_uploads():
    text = (ROOT / ".github" / "workflows" / "record-drop.yml").read_text()
    assert "anchor publish" not in text and "anchor record" in text
    assert "run-id: ${{ inputs.run_id }}" in text and "group: daily-drop" in text
