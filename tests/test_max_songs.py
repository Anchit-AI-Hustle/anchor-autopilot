"""As many songs as the quota allows, every day (Anchit, 2026-11-13: "ensure max song creation
and uploads"): the Mac makes the next day's songs overnight and the 08:37 run posts them, and no
two songs of one day share a visual world."""
from pathlib import Path

from anchor import scenes

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def test_no_two_songs_of_a_day_share_a_world():
    for seed in range(200):
        for recent in ([], ["hologram", "kaleidoscope", "neon wire"], ["pop art"]):
            worlds = [scenes.pick_world(seed, recent, slot) for slot in (1, 2, 3)]
            assert len(set(worlds)) == 3, (seed, recent, worlds)
            assert not set(worlds) & set(recent[-scenes.WORLD_GAP:])


def test_the_mac_makes_tomorrows_songs_overnight():
    text = (WF / "prerender.yml").read_text()
    assert '- cron: "37 21 * * *"' in text
    assert "gh workflow run daily.yml" in text and "dry_run=true" in text and "renderer=mac" in text
    assert '$T-2,$T-3,$T-4' in text, "slot 1 stays free for a queued Suno song"


def test_the_morning_run_posts_the_overnight_batch():
    text = (WF / "daily.yml").read_text()
    assert "from_run: ${{ steps.plan.outputs.from_run }}" in text
    assert "inputs.from_run ==" not in text and "inputs.from_run ||" not in text
    assert text.count("needs.plan.outputs.from_run") >= 5
    assert "python -m anchor has-drop --date" in text, "a song already out is never posted again"
    assert "steps.plan.outputs.from_run == ''" in text, "a run waiting for the Mac still posts a ready batch"
