"""The club cut of a songbook song: how acid, hard and psychedelic techno actually use a voice.

Anchit, 2026-11-15: "all songs dont need to have constant lyrics throughout the song - that is
probably stopping the best acid techno and hard techno flows and even in the drops".

What the genres do (artist/genres.toml, artist/songbook/GUIDE.md "Club cut"):
- hard techno and acid techno are built from the kick, the rumble and the 303. New elements
  come every 8 bars, sections are short, and a voice is a tool: a spoken line, a chant, a
  shouted one-shot, never a sung song from start to finish;
- hardstyle and rawstyle: a sparse intro, spoken or MC vocals in the mid-intro and the break,
  then the climax carried by the kick and the lead with no lyrics over it;
- ACE-Step 1.5 turns a section marker with no words under it into an instrumental passage,
  but an empty chorus becomes silence, so instrumental parts use drop, build-up and breakdown
  markers and every drop carries one short shout to keep the model from dropping out.

So for the chant lanes (hard tech and psy groups) the book's full song becomes:
one intro line, half a verse, a build-up on the hook, an instrumental drop with the title
shouted once, a breakdown (the bridge or the second verse, four lines), the hook again, the
second drop, a two-line outro. Roughly 20 sung bars in a 3 to 4 minute track: the music runs
the floor, the words land where a crowd can hear and shout them back. Rap and hip hop lanes
keep their full verses: there the words are the genre.
"""
from __future__ import annotations

import re

from .songbook import Song, bare_tags, sections


def _kind(tag: str) -> str:
    return tag.split(":")[0].strip().lower()


def _first(secs, *starts: str) -> list[str]:
    for tag, lines in secs:
        if _kind(tag).startswith(starts) and lines:
            return lines
    return []


def _nth_verse(secs, n: int) -> list[str]:
    verses = [lines for tag, lines in secs if _kind(tag).startswith("verse") and lines]
    return verses[n] if len(verses) > n else []


def _title_words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']+", title.lower()) if len(w) > 2}


def hook_lines(song: Song, n: int) -> list[str]:
    """Up to ``n`` hook lines, the one that carries the title first: the build-up must say the
    name the lyric check listens for."""
    secs = sections(song.lyrics)
    hook = _first(secs, "chorus", "hook", "final")
    if not hook:
        return [song.title]
    tw = _title_words(song.title)
    ranked = sorted(range(len(hook)), key=lambda i: (-len(tw & set(re.findall(r"[a-z']+", hook[i].lower()))), i))
    keep = sorted(ranked[:n])
    return [hook[i] for i in keep]


def _budget(lines: list[str], words: int, least: int = 2) -> list[str]:
    """Lines from the top until ``words`` are used (at least ``least`` lines): a dense rap-model
    verse gives two lines, a sung verse four."""
    out, n = [], 0
    for ln in lines:
        n += len(ln.split())
        if out and len(out) >= least and n > words:
            break
        out.append(ln)
    if len(out) > 2 and len(out) % 2:
        out.pop()   # whole couplets: a quote or a rhyme is never cut in half
    return out


def club_cut(song: Song, group: str = "") -> str:
    secs = sections(song.lyrics)
    intro = _first(secs, "intro")[:1]
    verse = _budget(_nth_verse(secs, 0)[:4], 36)
    turn = _budget(_first(secs, "bridge")[:4] or _nth_verse(secs, 1)[:4], 30)
    outro = _first(secs, "outro")[:2]
    shout = f"{song.title}!"
    parts = [("Intro", intro), ("Verse 1", verse), ("Build-Up", hook_lines(song, 2)), ("Drop", [shout]),
             ("Breakdown", turn), ("Build-Up", hook_lines(song, 4)), ("Drop", [shout]), ("Outro", outro)]
    if group == "hardtech":
        # hardstyle and rawstyle: the break ends on a spoken line before the climax (the MC)
        parts[5] = ("Build-Up", hook_lines(song, 1))
    text = "\n\n".join(f"[{tag}]\n" + "\n".join(lines) if lines else f"[{tag}]" for tag, lines in parts)
    return bare_tags(text)


def club_vocals_line(song: Song, room: int = 44) -> str:
    """The caption's vocal layer for a club cut: the same singer, used the way the genre uses a
    voice (kept short: the caption has a 1560 character budget)."""
    voice = song.voice if len(song.voice) <= room else song.voice[:room].rsplit(",", 1)[0].rsplit(" ", 1)[0]
    return f"Vocals: {voice}, natural English, sparse, drops instrumental"


def sung_words(sheet: str) -> int:
    return sum(len(ln.split()) for ln in sheet.splitlines() if ln.strip() and not ln.strip().startswith("["))


def rap_cut(song: Song) -> str:
    """A rap or hip hop song the way Outrun Your Shadow is built (GUIDE.md, Model A): every
    verse kept, vocals on about 40 percent of the track, and two drops that are music with one
    short chant, the second one right before the outro so the last lines are "spaced over the
    last drops". Book songs with a single drop get the second one; a drop line is cut to a chant
    of at most six words (Anchit, 2026-11-20: "songs like outrun your shadow with better drops")."""
    secs = sections(song.lyrics)
    drops = [lines for tag, lines in secs if _kind(tag).startswith("drop")]
    chant = next((ln for d in drops for ln in d), "") or f"{song.title}!"
    chant = " ".join(chant.split()[:6])
    out = [(tag.split(":")[0].strip().title(), [chant] if _kind(tag).startswith("drop") else lines)
           for tag, lines in secs]
    kinds = [_kind(t) for t, _ in out]
    if kinds.count("drop") < 2:
        outro = next((i for i, k in enumerate(kinds) if k.startswith("outro")), len(out))
        if outro and kinds[outro - 1] != "drop":
            out.insert(outro, ("Drop", [chant]))
        else:
            # the one drop already closes the song: the first hook gets its drop too
            hook = next((i for i, k in enumerate(kinds) if k.startswith(("hook", "chorus"))), None)
            if hook is not None and (hook + 1 >= len(kinds) or kinds[hook + 1] != "drop"):
                out.insert(hook + 1, ("Drop", [chant]))
    text = "\n\n".join(f"[{tag}]\n" + "\n".join(lines) if lines else f"[{tag}]" for tag, lines in out)
    return bare_tags(text)


def rap_vocals_line(vocals_line: str) -> str:
    """The rap caption's vocal layer plus how its drops land."""
    return f"{vocals_line}; the drops are kick and bass with one shouted chant"
