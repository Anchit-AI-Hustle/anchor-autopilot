"""The daily brief: what today's ANCHOR drop sounds and looks like.

Everything is seeded by the date, so a re-run of the same day reproduces the same
brief (handy for retries), while the catalog history keeps consecutive days distinct.
"""
from __future__ import annotations

from datetime import date as Date, datetime, timezone

from .config import Lane, Profile
from .music import SHAPES, arc, arrangement, section_names, structure
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
    active = profile.active_lanes
    for lane in active:
        if lane.id == last_lane and len(active) > 1:
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
    # length and shape are drawn for the day too: two records of the same length cut to the
    # same shape share a timeline, and that is most of what "sounds the same" means
    lo, hi = profile.music.get("duration_range_s") or (profile.music["duration_s"], profile.music["duration_s"])
    duration_s = r.randint(int(lo), int(hi))
    shape = r.choice(list(SHAPES))
    style = compose_style(profile, lane, r, bpm=bpm, duration_s=duration_s, shape=shape)

    used_titles = [d.get("title", "") for d in history] + list(profile.artist["existing_titles"])
    recent_titles = [d.get("title", "") for d in past[:10]] + list(profile.artist["existing_titles"])
    title = make_title(profile.titles, rng("anchor-title", day), used_titles, recent_titles)
    lyrics = vocal_sheet(profile, title, duration_s, tuple(style["textures"]), shape, rng("anchor-voice", day))

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
        "caption": style["caption"],
        "lyrics": lyrics,
        "vocal_style": "whispers and a shouted crowd chant",
        "textures": style["textures"],
        "mood": style["mood"],
        "special": style["special"],
        "negative": profile.music["negative"],
        "duration_s": duration_s,
        "shape": shape,
        "short_s": int(profile.music["short_s"]),
        "genre_line": lane.genre_line,
        "style_line": lane.style_line,
        "post_at": iso(post_time(profile, day)),
    }
    brief.update(describe(profile, brief))
    return brief


# How each section is voiced: whispered in the quiet sections, shouted as a crowd chant where
# the kick is in. The words sit under the section tag, the way an ACE-Step lyrics sheet is
# written, and the delivery rides in the tag so the model knows how to say them.
VOICE = {
    "intro": ("whispered voice", "whisper"),
    "build": ("whispered voice getting louder", "whisper2"),
    "drop": ("shouted crowd chant", "chant"),
    "breakdown": ("whispered voice", "whisper"),
    "build2": ("shouted crowd chant building", "shout"),
    "drop2": ("shouted crowd chant", "chant"),
    "outro": ("whispered voice", "whisper"),
}


def vocal_sheet(profile: Profile, title: str, duration_s: int, textures: tuple[str, ...], shape: str, r) -> str:
    """The lyrics field: every section's tag and direction, then its words.

    The drops chant the song's own title (so the record is named after what the crowd
    shouts) with a shout from the pool; the quiet sections whisper a line from the pool.
    Three whispers are drawn for the day and reused, so the song has a few phrases that
    come back rather than a new line every section. Every choice comes from ``r``.
    """
    voice = profile.music["voice"]
    whispers = r.sample(list(voice["whispers"]), k=3)
    shout = r.choice(list(voice["shouts"]))
    chant = title.upper()
    words = {
        "whisper": lambda i: whispers[i % len(whispers)],
        "whisper2": lambda i: f"{whispers[1]}, {whispers[1]}",
        "chant": lambda i: f"{chant}! {chant}!\n{shout.capitalize()}! {shout.capitalize()}! {shout.capitalize()}!",
        "shout": lambda i: f"{shout.capitalize()}! {shout.capitalize()}!",
    }
    names = section_names(duration_s, shape)
    out, quiet = [], 0
    for (tag, direction), name in zip(arrangement(duration_s, textures, shape), names):
        delivery, kind = VOICE.get(name, ("whispered voice", "whisper"))
        line = words[kind](quiet)
        if kind == "whisper":
            quiet += 1
        out.append(f"[{tag} - {direction}, {delivery}]\n{line}")
    return "\n\n".join(out)


def compose_style(profile: Profile, lane: Lane, r, *, bpm: int, duration_s: int, shape: str = "classic") -> dict:
    """The producer's brief, written the way a strong Suno/ACE-Step prompt is written.

    Nine layers, in this order, then compressed into prose: genre -> era/aesthetic -> mood
    with a trajectory -> tempo and groove -> instruments and when they enter -> vocals ->
    production -> arrangement arc (what happens over time) -> one special moment. The
    arranger (caption) and the songwriter (lyrics field, section tags with directions) are
    told the same story, so the render does not sound equally loud from first bar to last.

    The lane fixes genre, era, groove and production; the day rotates textures, mood arc
    and special moment from the lane's own lists, so consecutive days in one lane differ in
    the layers a listener notices most. Every choice comes from ``r`` and is reproducible.
    """
    music = profile.music
    textures = tuple(r.sample(list(lane.textures), k=3))
    mood = r.choice(lane.mood_arcs)
    special = r.choice(lane.special_moments)
    t0, t1, t2 = textures
    layers = [
        lane.caption,                                                   # 1 genre + core sound
        lane.era,                                                       # 2 era / sonic world
        f"Mood: {mood}. Feel: {music['feel']}",                         # 3 mood trajectory + the channel's feel
        f"{bpm} BPM, {lane.groove}",                                    # 4 tempo / rhythm
        f"Instruments: punchy kick and bouncing bass carry it; {t0} sits under the intro, "
        f"{t1} arrives with the build, {t2} owns the breakdown",        # 5 instruments + entry
        music["vocals"],                                                # 6 vocals
        f"Production: {lane.production}; {music['mastering']}",         # 7 production
        arc(duration_s, textures, shape),                               # 8 arrangement arc
        f"Special moment: {special}",                                   # 9 special moment
    ]
    caption = ". ".join(part.rstrip(".") for part in layers) + "."
    return {"caption": caption, "lyrics": structure(duration_s, textures, shape),
            "textures": list(textures), "mood": mood, "special": special}


def describe(profile: Profile, brief: dict, platform: str = "youtube") -> dict:
    """Title, tags and post copy from the brief (re-run after the tempo is measured).

    All three are built in seo.py so the words a search can find - the lane's genre phrase,
    the tempo, the artist - sit in the title and the first two lines of every description.
    ``tags`` cannot reach YouTube through Buffer (its YoutubePostMetadata has no tags field);
    it is returned for the release notes and for any uploader that can set it.
    """
    from .seo import description, tags, youtube_title
    lane = profile.lane(brief["lane"])
    return {"youtube_title": youtube_title(brief["title"], lane, int(brief["bpm"]), profile.artist["name"]),
            "tags": tags(profile, lane, int(brief["bpm"])),
            "description": description(profile, brief, platform),
            "description_short": description(profile, brief, "short"),
            "caption_instagram": description(profile, brief, "instagram")}
