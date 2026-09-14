"""The daily brief: what today's ANCHOR drop sounds and looks like.

Everything is seeded by the date, so a re-run of the same day reproduces the same
brief (handy for retries), while the catalog history keeps consecutive days distinct.
"""
from __future__ import annotations

from datetime import date as Date, datetime, timezone

from .config import Profile
from .titles import make_title
from .util import iso, rng, seed_from


def post_time(profile: Profile, day: str) -> datetime:
    hh, mm = (int(x) for x in profile.schedule["post_time_utc"].split(":"))
    d = Date.fromisoformat(day)
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=timezone.utc)


def make_brief(profile: Profile, day: str, history: list[dict], attempt: int = 0) -> dict:
    """Build the brief for ``day`` (YYYY-MM-DD). ``history`` is newest-first."""
    Date.fromisoformat(day)  # validates the format
    r = rng("anchor-brief", day)
    past = [d for d in history if d.get("date", "") < day]
    recent = past[:3]

    # sound lane: weighted, never the same lane two days running, recent lanes down-weighted
    last_lane = past[0]["lane"] if past else None
    recent_lanes = [d.get("lane") for d in recent]
    lanes, weights = [], []
    for lane in profile.lanes:
        if lane.id == last_lane and len(profile.lanes) > 1:
            continue
        lanes.append(lane)
        weights.append(max(1, lane.weight * 3 - 2 * recent_lanes.count(lane.id)))
    lane = r.choices(lanes, weights=weights, k=1)[0]

    # visual family: none of the last 3
    recent_fams = {d.get("family") for d in recent}
    fam_pool = [f for f in profile.families if f.id not in recent_fams] or list(profile.families)
    family = r.choice(fam_pool)

    # key: none of the last 3
    recent_keys = {d.get("key") for d in recent}
    keys = [k for k in profile.music["keys"] if k not in recent_keys] or profile.music["keys"]
    key = r.choice(keys)

    bpm = r.randint(lane.bpm[0], lane.bpm[1])
    textures = r.sample(list(lane.textures), k=min(2, len(lane.textures)))
    caption = ", ".join([lane.caption, *textures, profile.music["suffix"]])

    used_titles = [d.get("title", "") for d in history] + list(profile.artist["existing_titles"])
    recent_titles = [d.get("title", "") for d in past[:10]] + list(profile.artist["existing_titles"])
    title = make_title(profile.titles, rng("anchor-title", day), used_titles, recent_titles)

    brief = {
        "id": day,
        "date": day,
        "attempt": attempt,
        "seed": seed_from("anchor-audio", day, attempt) % 2_000_000_000,
        "title": title,
        "lane": lane.id,
        "lane_name": lane.name,
        "bpm": bpm,
        "key": key,
        "family": family.id,
        "family_name": family.name,
        "caption": caption,
        "negative": profile.music["negative"],
        "duration_s": int(profile.music["duration_s"]),
        "short_s": int(profile.music["short_s"]),
        "genre_line": lane.genre_line,
        "style_line": lane.style_line,
        "post_at": iso(post_time(profile, day)),
    }
    brief.update(describe(profile, brief))
    return brief


def describe(profile: Profile, brief: dict, platform: str = "youtube") -> dict:
    """Title, tags and post copy from the brief (re-run after the tempo is measured).

    Two things were wrong here and both went out on every post for weeks.

    The copy said "Full song out soon - this is the 45s cut" on every Short. The full tracks
    now exist, so that line told every viewer to wait for something already published, and
    pointed none of them at it.

    And ``tags`` is computed but cannot reach YouTube: Buffer's YoutubePostMetadata accepts
    title, category, privacy, madeForKids, isAiGenerated, notifySubscribers, embeddable,
    license, annotations and type - there is no tags field, so every tag computed here has
    been discarded in transit. It is still returned, for anything that CAN set it (a pass in
    Studio, or a future uploader), but nothing downstream should assume it reached YouTube.

    Instagram takes the same facts with different plumbing: a Reel caption cannot carry a
    clickable link, so the URL is stated as a bare domain and the hashtags do the discovery.
    """
    yt, name = profile.youtube, profile.artist["name"]
    bpm, key, title = brief["bpm"], brief["key"], brief["title"]
    lane = profile.lane(brief["lane"])
    site = profile.artist["site_url"].removeprefix("https://").rstrip("/")
    tags = list(dict.fromkeys([*yt["base_tags"], *lane.tags, f"hard techno {bpm} bpm"]))

    # No claim about vocals here. It said "Instrumental - no vocals", taken from the
    # generation caption - but nine of ten drops come in through queue from Suno, where that
    # caption never applied, and several carry a vocal hook: 2026-09-13 chants "project
    # mayhem" over and over. The line was on every post and was false for most of them.
    facts = [f"{lane.genre_line} \u00b7 {bpm} BPM \u00b7 {key}"]
    tail = [f"A new {name} track every day.", "Made with AI-assisted music tools."]

    if platform == "instagram":
        body = [f"{title} \u2014 {name}", "", *facts, "",
                f"Full track, free: {site}", *tail, "",
                # the two lists overlap; a repeated tag helps nothing and reads as sloppy
                " ".join(dict.fromkeys([*yt["hashtags"], *yt.get("instagram_hashtags", [])]))]
    else:
        body = [f"{title} \u2014 {name}",
                f"Full track, free: {site}", "",
                *facts, "", *tail, "",
                " ".join([*yt["hashtags"], "#shorts"])]

    return {"youtube_title": yt["title"].format(title=title)[:100],
            "tags": tags,
            "description": "\n".join(body)}
