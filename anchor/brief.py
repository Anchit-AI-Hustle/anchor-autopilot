"""The daily brief: what today's ANCHOR drop sounds and looks like.

Everything is seeded by the date, so a re-run of the same day reproduces the same
brief (handy for retries), while the catalog history keeps consecutive days distinct.
"""
from __future__ import annotations

from datetime import date as Date, datetime, timezone

from . import originality
from .config import Lane, Profile
from .music import SHAPES, arc, arrangement, section_names, structure
from .titles import make_title
from .util import iso, rng, seed_from, split_drop_id


def post_time(profile: Profile, day: str, slot: int = 1) -> datetime:
    """When a drop goes live: the day's first song at schedule.post_time_utc, later songs of
    the same day at schedule.extra_post_times_utc in order (Anchit, 2026-10-24: several songs
    a day). ``day`` may also be a drop id ("2026-10-25-2"), which carries its own slot."""
    day, id_slot = split_drop_id(day)
    slot = max(slot, id_slot)
    times = [profile.schedule["post_time_utc"], *profile.schedule.get("extra_post_times_utc", [])]
    hh, mm = (int(x) for x in times[min(slot, len(times)) - 1].split(":"))
    d = Date.fromisoformat(day)
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=timezone.utc)


def slot_group(profile: Profile, day: str, slot: int) -> str:
    """The genre group of a day's ``slot`` (1-based): schedule.slot_groups turned one step a day,
    so every day has each group once and a different group leads each day."""
    groups = list(profile.schedule.get("slot_groups") or [])
    if not groups:
        return "any"
    turn = Date.fromisoformat(day).toordinal()
    return groups[(turn + slot - 1) % len(groups)]


def slot_lanes(profile: Profile, day: str, slot: int) -> tuple[Lane, ...]:
    """The active lanes a slot may draw from: its genre group's, or all of them for "any" (and
    for a group with no active lane, so a slot never comes up empty)."""
    group = slot_group(profile, day, slot)
    active = profile.active_lanes
    picked = tuple(l for l in active if l.group == group) if group != "any" else ()
    return picked or active


def make_brief(profile: Profile, day: str, history: list[dict], attempt: int = 0) -> dict:
    """Build the brief for drop ``day``: a date (YYYY-MM-DD, the day's first song) or a date
    and slot (YYYY-MM-DD-2, its second). ``history`` is newest-first. Everything is seeded by
    the drop id, so the second song of a day is a different record, never a re-roll."""
    drop_id = day
    day, slot = split_drop_id(drop_id)
    Date.fromisoformat(day)  # validates the date
    r = rng("anchor-brief", drop_id)
    # earlier drops, including an earlier slot of the same day
    past = [d for d in history if (d.get("date", ""), d.get("id") or d.get("date", "")) < (day, drop_id)]
    recent = past[:3]

    # sound lane: weighted, never the same lane two days running, recent lanes down-weighted
    last_lane = past[0]["lane"] if past else None
    recent_lanes = [d.get("lane") for d in recent]
    lanes, weights = [], []
    active = slot_lanes(profile, day, slot)
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
    # never a title that is already a song anywhere (MusicBrainz, iTunes, Deezer), not just
    # on this channel (Anchit, 2026-10-24)
    check, title_report = originality.checker(), {}
    title = make_title(profile.titles, rng("anchor-title", drop_id), used_titles, recent_titles,
                       taken=check, report=title_report)
    lyrics = vocal_sheet(profile, title, duration_s, tuple(style["textures"]), shape, rng("anchor-voice", drop_id),
                         mode=lane.voice)

    brief = {
        "id": drop_id,
        "date": day,
        "slot": slot,
        "attempt": attempt,
        "seed": seed_from("anchor-audio", drop_id, attempt) % 2_000_000_000,
        "title": title,
        "lane": lane.id,
        "lane_name": lane.name,
        "genre_group": lane.group or "any",
        "bpm": bpm,
        "key": key,
        "family": family.id,
        "family_name": family.name,
        "caption": style["caption"],
        "lyrics": lyrics,
        "vocal_style": "rap verses and a shouted title chant hook" if lane.voice == "rap" else "whispers and a shouted crowd chant",
        "textures": style["textures"],
        "mood": style["mood"],
        "special": style["special"],
        "negative": lane.negative or profile.music["negative"],
        "duration_s": duration_s,
        "shape": shape,
        "short_s": int(profile.music["short_s"]),
        "genre_line": lane.genre_line,
        "style_line": lane.style_line,
        "post_at": iso(post_time(profile, day, slot)),
    }
    if check is not None:
        brief["title_check"] = title_report
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
# A rap lane raps where the chant lanes whisper over a building groove; the drops still chant
# the title, so the hook is the name of the record on every lane.
VOICE_RAP = {**VOICE,
             "build": ("rap verse, confident flow on the beat", "rap"),
             "breakdown": ("rap verse, laid-back flow over the groove", "rap"),
             "build2": ("rap verse, faster flow building to the hook", "rap")}


def section_tag(tag: str, kind: str = "") -> str:
    """The tag a lyrics sheet uses for a section: a rap section is a Verse, the rest keep their name."""
    if kind == "rap":
        return "Verse"
    return {"build": "Build-Up"}.get(tag, tag.capitalize())


def vocal_sheet(profile: Profile, title: str, duration_s: int, textures: tuple[str, ...], shape: str, r,
                mode: str = "chant") -> str:
    """The lyrics field: every section's tag and direction, then its words.

    The drops chant the song's own title (so the record is named after what the crowd
    shouts) with a shout from the pool; the quiet sections whisper a line from the pool.
    Three whispers are drawn for the day and reused, so the song has a few phrases that
    come back rather than a new line every section. A rap lane (``mode="rap"``) raps four
    bars in each build and breakdown, drawn without repeats from the profile's own bars.
    Every choice comes from ``r``.
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
    voices = VOICE
    if mode == "rap":
        bank = list(voice["rap"])
        bars = r.sample(bank, k=min(12, len(bank)))
        words["rap"] = lambda i: "\n".join(bars[(4 * i + j) % len(bars)] for j in range(4))
        voices = VOICE_RAP
    names = section_names(duration_s, shape)
    out, quiet, verse = [], 0, 0
    for (tag, direction), name in zip(arrangement(duration_s, textures, shape), names):
        delivery, kind = voices.get(name, ("whispered voice", "whisper"))
        line = words[kind](verse if kind == "rap" else quiet)
        if kind == "whisper":
            quiet += 1
        if kind == "rap":
            verse += 1
        # a bare section tag: a direction or delivery note written into the sheet gets SUNG
        # (2026-10-25: "for eight to sixteen bars ... rap verse, laid back flow over the groove").
        # The arrangement and the delivery live in the caption (lane vocals, arc) instead.
        out.append(f"[{section_tag(tag, kind)}]\n{line}")
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
        lane.vocals or music["vocals"],                                 # 6 vocals
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
