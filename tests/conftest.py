import re
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def fast_profile(tmp_path):
    """The real profile with short durations so renders stay quick in CI."""
    from anchor.config import load_profile
    text = (ROOT / "artist" / "anchor.toml").read_text()
    text = re.sub(r"^duration_s = \d+", "duration_s = 36", text, flags=re.M)
    text = re.sub(r"^short_s = \d+", "short_s = 16", text, flags=re.M)
    path = tmp_path / "anchor.toml"
    path.write_text(text)
    return load_profile(path)


@pytest.fixture()
def site_dir(tmp_path):
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    # start from the shipped catalog but with no drops: the live one gains a drop every day,
    # and a newer drop than the test's would change what the pipeline treats as "latest"
    cat = json.loads((ROOT / "site" / "data" / "catalog.json").read_text())
    cat["drops"] = []
    (site / "data" / "catalog.json").write_text(json.dumps(cat, indent=2))
    return site


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path, monkeypatch):
    """No test reads the real release queue.

    The queue holds references to Suno songs that the robot fetches at release time, so
    a test that picked it up would both change what it released and hit the network.
    """
    q = tmp_path / "_isolated_queue"          # not "queue": tests make their own
    q.mkdir()
    monkeypatch.setattr("anchor.pipeline.QUEUE", q)
    monkeypatch.setattr("anchor.queue.QUEUE", q)
    # the queue now refuses to release anything the website already shows, so a test that
    # saw the real catalogue would find its own fixture songs "already posted"
    monkeypatch.setattr("anchor.config.CATALOG_PATH", tmp_path / "_no_catalog.json")
    return q
