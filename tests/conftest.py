import re
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
    shutil.copy(ROOT / "site" / "data" / "catalog.json", site / "data" / "catalog.json")
    return site
