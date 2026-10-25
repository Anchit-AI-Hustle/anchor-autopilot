"""How many songs a day the channel can take (Anchit, 2026-10-24: "max possible", not two).

The ceiling is YouTube's, not ours: the Data API gives a project 10,000 units a day, reset at
midnight Pacific time, and an upload costs 1,600 (thumbnail and playlist ~100 more). A song
whose full video AND Short go up through the API costs ~3,300; with the Short sent through
Buffer (which posts to YouTube without touching our API quota) it costs ~1,700.

So every run makes the day's next missing song (YYYY-MM-DD, then -2, -3 ...) only while the
Pacific day's estimated spend plus the next song stays inside the budget. When Buffer works
that is five songs a day; when it does not, the estimate rises to the API cost and the channel
falls back to two, never to a half-posted song with its Short refused for quota.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
UPLOAD = 1600          # videos.insert
EXTRAS = 100           # thumbnails.set + playlistItems.insert
COST_API_SHORT = 2 * UPLOAD + EXTRAS      # full video and Short through the API
COST_BUFFER_SHORT = UPLOAD + EXTRAS       # full video through the API, Short through Buffer


def day_start(now: datetime) -> datetime:
    """Start of the YouTube quota day (midnight Pacific) that ``now`` falls in, in UTC."""
    local = now.astimezone(PACIFIC)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def cost(drop: dict) -> int:
    """Estimated API units a published drop used."""
    if drop.get("youtube_via") != "youtube_api":
        return 0                                  # Buffer-only drops never touch the API
    return COST_BUFFER_SHORT if drop.get("short_via") == "buffer" else COST_API_SHORT


def _when(drop: dict) -> datetime | None:
    raw = drop.get("created_at") or ""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def used(drops: list[dict], now: datetime) -> int:
    start = day_start(now)
    return sum(cost(d) for d in drops if (w := _when(d)) and start <= w <= now + timedelta(hours=1))


def next_cost(drops: list[dict], shorts_via_buffer: bool = True) -> int:
    """What the next song is expected to cost: the Buffer price while Shorts are set to go
    through Buffer and the last attempt did not fail; the full API price otherwise."""
    if not shorts_via_buffer:
        return COST_API_SHORT
    api = [d for d in drops if d.get("youtube_via") == "youtube_api" and _when(d)]
    if api and max(api, key=_when).get("short_buffer_failed"):
        return COST_API_SHORT
    return COST_BUFFER_SHORT


def next_drop(drops: list[dict], day: str, slots: int, budget: int, now: datetime,
              shorts_via_buffer: bool = True) -> tuple[str | None, str]:
    """The drop id the next run should make for ``day``, or None and why not."""
    done = {d.get("id") for d in drops if d.get("status") not in ("dry-run", "error", "planned")}
    ids = [day] + [f"{day}-{n}" for n in range(2, slots + 1)]
    todo = next((i for i in ids if i not in done), None)
    if todo is None:
        return None, f"all {slots} songs for {day} are out"
    spent, nxt = used(drops, now), next_cost(drops, shorts_via_buffer)
    if spent + nxt > budget:
        return None, (f"YouTube quota: {spent} units used today (Pacific day), the next song needs ~{nxt}, "
                      f"budget {budget}; it waits for the reset at midnight Pacific")
    return todo, f"{todo}: {spent} + ~{nxt} of {budget} units"


def plan(drops: list[dict], day: str, slots: int, budget: int, now: datetime,
         shorts_via_buffer: bool = True) -> tuple[list[str], str]:
    """Every drop id one run should make for ``day`` at once, in order: the day's missing
    slots, as many as the quota budget still has room for (renders run side by side, so a
    late start never costs the day its songs)."""
    done = {d.get("id") for d in drops if d.get("status") not in ("dry-run", "error", "planned")}
    ids = [day] + [f"{day}-{n}" for n in range(2, slots + 1)]
    todo = [i for i in ids if i not in done]
    if not todo:
        return [], f"all {slots} songs for {day} are out"
    spent, each = used(drops, now), next_cost(drops, shorts_via_buffer)
    room = max(0, (budget - spent) // each)
    if room == 0:
        return [], (f"YouTube quota: {spent} units used today (Pacific day), a song needs ~{each}, "
                    f"budget {budget}; it waits for the reset at midnight Pacific")
    picked = todo[:room]
    return picked, f"{', '.join(picked)}: {spent} + {len(picked)} x ~{each} of {budget} units"


def room_for_one(drops: list[dict], budget: int, now: datetime, shorts_via_buffer: bool = True) -> tuple[bool, str]:
    """Whether one more song fits today's budget (checked again before each publish)."""
    spent, each = used(drops, now), next_cost(drops, shorts_via_buffer)
    return spent + each <= budget, f"{spent} + ~{each} of {budget} units"
