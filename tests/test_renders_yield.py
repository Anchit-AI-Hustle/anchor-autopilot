"""Songs are made in the background and never slow the Mac (Anchit, 2026-11-21: "ensure all
song creations happen in the background without affecting cpu usage or gpu usage or speed of
laptop at all")."""
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
YIELD = ROOT / "tools" / "mac-yield.sh"


def test_the_mac_renders_at_background_priority_with_time_to_pause():
    daily = (ROOT / ".github" / "workflows" / "daily.yml").read_text()
    studio = (ROOT / ".github" / "workflows" / "studio.yml").read_text()
    assert "caffeinate -i taskpolicy -b nice -n 19 python -m anchor make" in daily
    assert "caffeinate -i taskpolicy -b nice -n 19 python -m anchor studio" in studio
    assert "renderer == 'mac' && 480" in daily, "a paused render is not killed by the job limit"


def test_the_heartbeat_keeps_the_pause_watcher_running():
    setup = (ROOT / "scripts" / "mac-runner-setup.sh").read_text()
    assert "mac-yield.sh" in setup and "--loop" in setup
    text = YIELD.read_text()
    import re
    pattern = re.search(r"PATTERN='([^']+)'", text).group(1)
    paused = ["/Users/a/anchor-gpu/acestep.cpp/build/ace-synth --request gen.json",
              "/Users/a/anchor-gpu/acestep.cpp/build/ace-lm --models m",
              "/opt/homebrew/Cellar/python@3.12/Python.app/Contents/MacOS/Python -m anchor make --date 2026-11-20",
              "/Users/a/runner-venv/bin/python -m anchor studio --request r.json",
              "ffmpeg -y -i build/2026-11-20/master.wav out.wav",
              "/Users/a/anchor-gpu/cinematic/venv/bin/python /Users/a/anchor-gpu/cinematic/repo/tools/cinematic/worker.py"]
    left = ["/bin/zsh -l -c grep ace-synth notes.txt && echo python -m anchor make",
            "caffeinate -i python -m anchor make --date 2026-11-20",
            "vim tools/mac-yield.sh", "ffmpeg -i ~/Movies/holiday.mov out.mp4"]
    assert all(re.search(pattern, c) for c in paused), [c for c in paused if not re.search(pattern, c)]
    assert not any(re.search(pattern, c) for c in left), [c for c in left if re.search(pattern, c)]


@pytest.mark.skipif(not shutil.which("ioreg"), reason="macOS only: reads the keyboard and mouse idle time")
def test_renders_pause_while_the_mac_is_used_and_carry_on_when_idle(tmp_path):
    fake = subprocess.Popen(["bash", "-c", "exec -a /tmp/yieldtest/ace-synth sleep 120"])
    try:
        time.sleep(0.5)
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(tmp_path), "ANCHOR_GPU_DIR": str(tmp_path)}
        state = lambda: subprocess.run(["ps", "-o", "stat=", "-p", str(fake.pid)], capture_output=True, text=True).stdout.strip()
        subprocess.run(["bash", str(YIELD)], env={**env, "ANCHOR_YIELD_IDLE_S": "999999999"}, check=True)
        assert state().startswith("T"), "in use: the render is paused"
        subprocess.run(["bash", str(YIELD)], env={**env, "ANCHOR_YIELD_IDLE_S": "0"}, check=True)
        assert not state().startswith("T"), "idle: the render carries on"
        assert "STOP" in (tmp_path / "yield.log").read_text()
    finally:
        fake.kill()
