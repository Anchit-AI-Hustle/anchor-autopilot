"""The daily brief: what today's ANCHOR drop sounds and looks like.

Everything is seeded by the date, so a re-run of the same day reproduces the same
brief (handy for retries), while the catalog history keeps consecutive days distinct.
"""
from __future__ import annotations

from datetime import date as Date, datetime, timezone

from . import originality, themes
from . import songbook
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
    # schedule.first_slot_group (Anchit, 2026-11-10: "if you are making hard tech, then ensure
    # hard tech songs are made"): the day's first song, the one that most often makes it, is
    # always that group; the other slots turn through the rest one step a day
    first = profile.schedule.get("first_slot_group")
    if first and first in groups:
        if slot == 1:
            return first
        rest = [g for g in groups if g != first] or groups
        return rest[(turn + slot - 2) % len(rest)]
    return groups[(turn + slot - 1) % len(groups)]


def slot_lanes(profile: Profile, day: str, slot: int) -> tuple[Lane, ...]:
    """The active lanes a slot may draw from: its genre group's, or all of them for "any" (and
    for a group with no active lane, so a slot never comes up empty)."""
    group = slot_group(profile, day, slot)
    active = profile.active_lanes
    picked = tuple(l for l in active if l.group == group) if group != "any" else ()
    return picked or active


def make_brief(profile: Profile, day: str, history: list[dict], attempt: int = 0,
               avoid_titles: tuple[str, ...] = ()) -> dict:
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
    # the song itself: a whole song from the songbook, written by a songwriter and used once
    # (Anchit, 2026-11-07: "proper theme selection and lyrics ... written as humans ... choose
    # the song name based on theme and lyrics"); the line-pool themes only when the book is dry
    check, title_report = originality.checker(), {}
    song = songbook.pick(songbook.load(), lane.group or "any", rng("anchor-song", drop_id), history,
                         used_titles=[d.get("title", "") for d in history] + list(profile.artist["existing_titles"]),
                         avoid_titles=tuple(avoid_titles), taken=check, report=title_report,
                         prefer=_cinematic_ready())
    theme = None
    if song is not None:
        # a long song (Model B, Kindness Needs Truth) gets the time to sing every word (2026-11-08)
        duration_s = max(duration_s, songbook.length_s(song, int(lo), int(hi),
                                                       int(profile.music.get("max_duration_s", 300))))
    if song is None:
        # what the song is about: a theme none of the last 20 songs had (artist/themes.toml)
        theme = themes.pick(themes.load(), rng("anchor-theme", drop_id), past,
                            used_titles=[d.get("title", "") for d in history] + list(profile.artist["existing_titles"]),
                            avoid_titles=tuple(avoid_titles))
    sound = pick_palette(profile, rng("anchor-sound", drop_id), past, group=lane.group or "")
    style = compose_style(profile, lane, r, bpm=bpm, duration_s=duration_s, shape=shape,
                          story=songbook.short(song.about, 100) if song else theme.idea, sound=sound,
                          vocals=songbook.vocals_line(song) if song else None)

    used_titles = [d.get("title", "") for d in history] + list(profile.artist["existing_titles"])
    # a name the singer could not say clearly on an earlier take is not tried again for this song
    used_titles += list(avoid_titles)
    recent_titles = [d.get("title", "") for d in past[:10]] + list(profile.artist["existing_titles"])
    # never a title that is already a song anywhere (MusicBrainz, iTunes, Deezer), not just
    # on this channel (Anchit, 2026-10-24); a songbook song is named by its own hook
    if song is not None:
        title = song.title
        title_report.update(source="songbook", song=song.id)
    else:
        # the name comes from the theme, sharing no word with any earlier ANCHOR title (Anchit,
        # 2026-10-31); only when every title of the theme is taken does the old word list name it
        title = themes.title(theme, rng("anchor-title", drop_id), used_titles, taken=check, report=title_report,
                             recent_titles=[d.get("title", "") for d in past])
    if title is None:
        title = make_title(profile.titles, rng("anchor-title", drop_id), used_titles, recent_titles,
                           taken=check, report=title_report)
    if song is not None:
        lyrics = song.lyrics
    else:
        lyrics = vocal_sheet(profile, title, duration_s, tuple(style["textures"]), shape, rng("anchor-voice", drop_id),
                             mode=lane.voice, theme=theme, group=lane.group or "",
                             rotate=Date.fromisoformat(day).toordinal() * 3 + (slot - 1) * 7)

    brief = {
        "id": drop_id,
        "date": day,
        "slot": slot,
        "attempt": attempt,
        "seed": seed_from("anchor-audio", drop_id, attempt) % 2_000_000_000,
        "title": title,
        "lane": lane.id,
        "lane_name": lane.name,
        "theme": song.id if song else theme.id,
        "sound": sound,
        "theme_name": song.title if song else theme.name,
        "theme_idea": song.about if song else theme.idea,
        "form": song.form if song else "chant",
        "model": song.model if song else "",
        "genre_group": lane.group or "any",
        "bpm": bpm,
        "key": key,
        "family": family.id,
        "family_name": family.name,
        "caption": style["caption"],
        "lyrics": lyrics,
        "vocal_style": (song.voice if song else
                        "rap verses and a shouted title chant hook" if lane.voice == "rap" else "whispers and a shouted crowd chant"),
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


def _couplets(lines: list[str], r, k: int | None = None, rotate: int | None = None) -> list[str]:
    """Rhymed couplets (lines 0-1, 2-3, ...) drawn as pairs, each joined as two sung lines.
    With ``rotate`` a genre bank is walked in turn from that point (consecutive songs start
    further on), so a week of songs spreads over the whole bank instead of drawing the same
    favourite couplets again."""
    pairs = [lines[i:i + 2] for i in range(0, len(lines) - 1, 2)]
    if rotate is not None and pairs:
        start = rotate % len(pairs)
        pairs = (pairs[start:] + pairs[:start])[:k or len(pairs)]
    else:
        pairs = r.sample(pairs, k=min(k or len(pairs), len(pairs)))
    return ["\n".join(dict.fromkeys(p)) for p in pairs]


def vocal_sheet(profile: Profile, title: str, duration_s: int, textures: tuple[str, ...], shape: str, r,
                mode: str = "chant", theme=None, group: str = "", rotate: int = 0) -> str:
    """The lyrics field: every section's tag, then its words.

    The words are a person's (Anchit, 2026-11-02: "lyrics and voices too robotic ... proper
    humanized song lyrics based on the genre ... emotion generating or wacky gangster verses or
    hardcore heavy bars or chants and whispers of shlokas"). The theme gives three rhymed
    couplets about a moment in people's lives (artist/themes.toml); the genre group adds its
    own voice from ``[music.lyric_styles.<group>]``:
      psy       Sanskrit shlokas and mantras whispered and chanted in the intro, breakdown, outro
      hardtech  hardcore heavy MC bars in the builds and heavy shouts in the drops
      rap       wacky gangster verses, two couplets a verse
      hiphop    heavy bars: one story couplet of the theme, one heavy couplet, every verse
    The drops chant the title; the title also closes the breakdown, the shouted build and every
    verse, because a drop chant is often left unsung. Every choice comes from ``r``.
    """
    voice = profile.music["voice"]
    style = (profile.music.get("lyric_styles") or {}).get(group) or {}
    pool_w = list(theme.whispers) if theme else list(voice["whispers"])
    # the drops answer the title with the theme's own crowd shouts, so they differ song to song
    pool_s = list(theme.chants if theme else voice["shouts"])
    sung = _couplets(pool_w, r, 3) if theme else [r.choice(pool_w) for _ in range(3)]
    while len(sung) < 3:
        sung.append(sung[-1])
    shout = r.choice(pool_s)
    chant = title.upper()
    quiet_lines = [sung[0], sung[2], sung[0]]      # the intro couplet comes back in the outro
    build = sung[1]
    if style.get("mantras"):
        # psy: the quiet parts whisper and chant shlokas, the build sings the theme's couplet
        m = _couplets(style["mantras"], r, 2, rotate=rotate)
        quiet_lines = [m[0], f"{m[1] if len(m) > 1 else m[0]}\n{sung[2]}", m[0]]
    mc = None
    if style.get("bars") and mode != "rap":
        # hard techno: an MC's heavy bars drive the builds
        mc = _couplets(style["bars"], r, 2, rotate=rotate)
        build = mc[0]
    words = {
        "whisper": lambda i: quiet_lines[i] if i < len(quiet_lines) else quiet_lines[-1],
        "whisper2": lambda i: build,
        "chant": lambda i: f"{chant}! {chant}!\n{shout.capitalize()}! {shout.capitalize()}! {shout.capitalize()}!",
        "shout": lambda i: mc[-1] if mc else f"{shout.capitalize()}! {shout.capitalize()}!",
    }
    voices = VOICE
    if mode == "rap":
        story = _couplets(list(theme.rap) if theme else list(voice["rap"]), r)
        if style.get("bars") and style.get("mix_story"):
            heavy = _couplets(style["bars"], r, rotate=rotate)   # hip hop: story then a heavy couplet
            verses = [f"{story[i % len(story)]}\n{heavy[i % len(heavy)]}" for i in range(6)]
        elif style.get("bars"):
            gang = _couplets(style["bars"], r, rotate=rotate)   # rap: a wacky gangster couplet
            verses = [f"{gang[i % len(gang)]}\n{story[i % len(story)]}" for i in range(6)]   # then the story
        else:
            verses = [f"{story[(2 * i) % len(story)]}\n{story[(2 * i + 1) % len(story)]}" for i in range(6)]
        words["rap"] = lambda i: verses[i % len(verses)]
        voices = VOICE_RAP
    names = section_names(duration_s, shape)
    out, quiet, verse = [], 0, 0
    for (tag, direction), name in zip(arrangement(duration_s, textures, shape), names):
        delivery, kind = voices.get(name, ("sung voice", "whisper"))
        line = quiet_lines[0] if name == "outro" and kind == "whisper" else words[kind](verse if kind == "rap" else quiet)
        if kind == "whisper":
            quiet += 1
        if kind == "rap":
            verse += 1
        # a bare section tag: a direction or delivery note written into the sheet gets SUNG
        # (2026-10-25). The title also closes the breakdown, the shouted build and every verse:
        # the drop chant is often left unsung (2026-11-01, Feathers And Drums).
        if kind in ("rap", "shout") or (kind == "whisper" and name not in ("intro", "outro")):
            line = f"{line}\n{title}"
        out.append(f"[{section_tag(tag, kind)}]\n{line}")
    return "\n\n".join(out)


PALETTE_PARTS = ("lead", "bass", "drums", "melody", "chords")
PALETTE_GAP = 8          # a lead sound or a melody shape comes back only after this many songs


def pick_palette(profile: Profile, r, history: list[dict], gap: int = PALETTE_GAP,
                 group: str = "") -> dict | None:
    """The sound of one song: a lead, a bass, a drum kit, a melody shape and a chord feel from
    ``[music.palette.<group>]`` (the lane's genre group: a hip hop song gets boom bap or trap
    drums and an 808, a psy song a rolling psy bassline), else ``[music.palette]``. No lead or
    melody of the last ``gap`` songs, no bass, kit or chords of the last few, and never the
    exact set of an earlier song. None without a palette."""
    pal = profile.music.get("palette")
    if not pal:
        return None
    if isinstance(pal.get(group), dict):
        pal = pal[group]
    banks = {"lead": pal["leads"], "bass": pal["basses"], "drums": pal["drums"], "melody": pal["melodies"],
             "chords": pal["chords"]}
    gaps = {"lead": gap, "melody": gap, "bass": 4, "drums": 4, "chords": 3}
    past = [d.get("sound") or {} for d in history]
    seen = {tuple(p.get(k) for k in PALETTE_PARTS) for p in past if p}
    for _ in range(200):
        out = {}
        for part, bank in banks.items():
            recent = {p.get(part) for p in past[:gaps[part]]}
            out[part] = r.choice([x for x in bank if x not in recent] or list(bank))
        if tuple(out[k] for k in PALETTE_PARTS) not in seen:
            return out
    return out


def compose_style(profile: Profile, lane: Lane, r, *, bpm: int, duration_s: int, shape: str = "classic",
                  story: str = "", sound: dict | None = None, vocals: str | None = None) -> dict:
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
    # a human voice named the way ACE-Step reads it (2026-11-02): drawn after the other picks so
    # the textures, mood and moment of a day stay what they were
    voice = music.get("voice", {})
    singer = r.choice(voice.get("singers") or ["warm natural human vocal"])
    rapper = r.choice(voice.get("rappers") or ["natural human rapper"])
    t0, t1, t2 = textures
    layers = [
        lane.caption,                                                   # 1 genre + core sound
        lane.era,                                                       # 2 era / sonic world
        f"Mood: {mood}{f', about {story}' if story else ''}. Feel: {music['feel']}",   # 3 mood + what it is about
        f"{bpm} BPM, {lane.groove}",                                    # 4 tempo / rhythm
        (f"Instruments: {sound['drums']}, {sound['bass']}, {sound['lead']} playing {sound['melody']} "
         f"over {sound['chords']}; {t0} intro, {t1} build, {t2} breakdown"
         if sound else
         f"Instruments: punchy kick and bouncing bass carry it; {t0} sits under the intro, "
         f"{t1} arrives with the build, {t2} owns the breakdown"),      # 5 instruments + entry
        vocals or (lane.vocals or ((music.get("lyric_styles") or {}).get(lane.group or "") or {}).get("vocals")
                   or music["vocals"]).format(singer=singer, rapper=rapper),   # 6 vocals: a person
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
    out = {"youtube_title": youtube_title(brief["title"], lane, int(brief["bpm"]), profile.artist["name"]),
           "tags": tags(profile, lane, int(brief["bpm"])),
           "description": description(profile, brief, platform),
           "description_short": description(profile, brief, "short"),
           "caption_instagram": description(profile, brief, "instagram")}
    return apply_overrides(out, brief.get("overrides") or {})


def apply_overrides(out: dict, ov: dict) -> dict:
    """What was typed on the Sync with Suno page wins: the YouTube title, the description (the
    Short and the Reel keep their own pointer lines) and the hashtags (the last line of each)."""
    if ov.get("youtube_title"):
        out["youtube_title"] = ov["youtube_title"].strip()[:100]
    if ov.get("description"):
        out["description"] = ov["description"].strip()[:4900]
    tags = " ".join(t if t.startswith("#") else f"#{t}" for t in str(ov.get("hashtags") or "").replace(",", " ").split())
    if tags:
        for k in ("description", "caption_instagram"):
            body = out[k].rstrip().rsplit("\n", 1)
            out[k] = (body[0] if body[-1].lstrip().startswith("#") else out[k].rstrip()) + "\n" + tags
        short = out["description_short"].rstrip().rsplit("\n", 1)
        short_tags = " ".join(dict.fromkeys([*tags.split()[:2], "#shorts"]))
        out["description_short"] = (short[0] if short[-1].lstrip().startswith("#") else out["description_short"]) + "\n" + short_tags
    return out


def _cinematic_ready() -> set[str]:
    """Songbook songs whose cinematic shots are all made on the Mac (empty anywhere else)."""
    try:
        from .cinematic import ready_ids
        return ready_ids()
    except Exception:  # noqa: BLE001 - a missing folder never stops a drop
        return set()
