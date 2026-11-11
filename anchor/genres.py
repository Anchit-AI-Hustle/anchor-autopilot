"""What every genre is made of, how two genres fuse, and how songs become a set.

Anchit, 2026-11-10: "completely learn about each and every genre of music ... and about
mashups so that you can create the perfect type of music, songs, videos and sets". The facts
live in artist/genres.toml and artist/mashups.toml, researched and sourced; this module
reads them and gives the rest of the robot three things:

- ``lane_problems``: a lane in anchor.toml names its genres, and its tempo, words and
  negatives are checked against them, so a lane called hard tech can never again be briefed
  as tech house (2026-11-10).
- ``camelot`` and ``key_distance``: harmonic mixing on the Camelot wheel.
- ``set_order``: the weekly and monthly sets, ordered so the tempo climbs to a peak about
  two-thirds in and each next song sits in a compatible key where one is close in tempo.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENRES_PATH = ROOT / "artist" / "genres.toml"
MASHUPS_PATH = ROOT / "artist" / "mashups.toml"


@dataclass(frozen=True)
class Genre:
    id: str
    name: str
    family: str
    bpm: tuple[int, int]
    prompt: tuple[str, ...]
    negative: tuple[str, ...]
    visual: str
    sources: tuple[str, ...]
    confidence: str = "ok"


@lru_cache(maxsize=1)
def load() -> dict[str, Genre]:
    raw = tomllib.loads(GENRES_PATH.read_text())
    out = {}
    for g in raw["genre"]:
        out[g["id"]] = Genre(id=g["id"], name=g["name"], family=g["family"], bpm=(int(g["bpm"][0]), int(g["bpm"][1])),
                             prompt=tuple(g["prompt"]), negative=tuple(g["negative"]), visual=g["visual"],
                             sources=tuple(g["sources"]), confidence=g.get("confidence", "ok"))
    return out


@lru_cache(maxsize=1)
def mashups() -> dict:
    return tomllib.loads(MASHUPS_PATH.read_text())


def problems() -> list[str]:
    """What is wrong with the two files themselves (the tests hold them to this)."""
    out, gs = [], load()
    for g in gs.values():
        if not (40 <= g.bpm[0] <= g.bpm[1] <= 230):
            out.append(f"{g.id}: bpm {g.bpm}")
        if len(g.prompt) < 3 or not g.negative or not g.sources:
            out.append(f"{g.id}: needs 3+ prompt words, negatives and a source")
        if not all(s.startswith("https://") for s in g.sources):
            out.append(f"{g.id}: sources must be https links")
        clash = {p.lower() for p in g.prompt} & {n.lower() for n in g.negative}
        if clash:
            out.append(f"{g.id}: {clash} is both wanted and unwanted")
    for f in mashups().get("fusion", []):
        for side in ("base", "top"):
            if f[side] not in gs:
                out.append(f"fusion {f['id']}: unknown genre {f[side]}")
    return out


def _text(lane) -> str:
    return " ".join([lane.caption, lane.genre_line, lane.style_line]).lower()


def tempo_range(ids) -> tuple[int, int]:
    """The combined tempo range of genres; a hip hop genre counts at double time too, since a
    half-time flow at 80-100 rides 160-200 (mashups.toml [tempo] pairs)."""
    gs = load()
    spans = []
    for i in ids:
        g = gs[i]
        spans.append(g.bpm)
        if g.family == "hiphop":
            spans.append((g.bpm[0] * 2, g.bpm[1] * 2))
    return min(a for a, _ in spans), max(b for _, b in spans)


def lane_problems(lane, genre_ids: list[str], tempo_like: list[str] = ()) -> list[str]:
    """Why a lane does not make the genres it names (empty when it does): its tempo must sit
    inside the genres' combined range (plus ``tempo_like``: genres whose speed the lane borrows,
    such as hard techno pushed to hardtek tempo), its words must carry at least one signature
    phrase of each genre, never a phrase that makes one of them sound wrong, and its negative
    prompt must never ban a genre's own signature."""
    gs = load()
    unknown = [g for g in [*genre_ids, *tempo_like] if g not in gs]
    if not genre_ids or unknown:
        return [f"{lane.id}: genres {unknown or 'missing'}"]
    named = [gs[g] for g in genre_ids]
    lo, hi = tempo_range([*genre_ids, *tempo_like])
    out = []
    if not (lo <= lane.bpm[0] and lane.bpm[1] <= hi):
        out.append(f"{lane.id}: bpm {lane.bpm} outside {', '.join([*genre_ids, *tempo_like])} ({lo}-{hi})")
    text, neg = _text(lane), (lane.negative or "").lower()
    for g in named:
        if not any(p.lower() in text for p in g.prompt):
            out.append(f"{lane.id}: says none of {g.name}'s signature ({', '.join(g.prompt[:4])})")
        wrong = [n for n in g.negative if n.lower() in lane.caption.lower()]
        if wrong:
            out.append(f"{lane.id}: briefs {wrong}, which makes {g.name} sound wrong")
        banned = [p for p in g.prompt if p.lower() in neg]
        if banned:
            out.append(f"{lane.id}: its negative prompt bans {g.name}'s {banned}")
    return out


def label(genre_ids: list[str]) -> str:
    """A fusion's name from its genres, base first: "Drift Phonk x Hard Techno"."""
    gs = load()
    names = [gs[g].name for g in genre_ids if g in gs]
    return " x ".join(reversed(names)) if len(names) > 1 else (names[0] if names else "")


# ---------------------------------------------------------------- harmonic mixing
def camelot(key: str | None) -> str | None:
    """'F minor' -> '4A' (None when the key is unknown)."""
    if not key:
        return None
    return mashups()["camelot"]["codes"].get(" ".join(key.split()))


def key_distance(a: str | None, b: str | None) -> int:
    """Steps between two keys on the wheel: 0 for the same code or its relative (8A/8B),
    1 for a neighbour, up to 6; 9 when either key is unknown."""
    ca, cb = camelot(a), camelot(b)
    if not ca or not cb:
        return 9
    na, nb = int(ca[:-1]), int(cb[:-1])
    d = abs(na - nb) % 12
    d = min(d, 12 - d)
    return d + (1 if ca[-1] != cb[-1] and d else 0)


def tempo_ok(a: float, b: float) -> bool:
    """Two tempos a DJ can mix: within the stretch limit, directly or at half or double time."""
    lim = mashups()["tempo"]["max_stretch"]
    return any(abs(a * f - b) / b <= lim for f in (1.0, 2.0, 0.5))


def set_order(tracks: list[dict]) -> list[dict]:
    """Order a set: the tempo climbs from the slowest song to the fastest, which plays about
    two-thirds in (mashups.toml [sets] peak_at), then the rest step back down to close. Among
    songs of a near tempo the next one is the closest key on the Camelot wheel."""
    # a set of four or fewer songs has no room for a peak and a come-down: it just climbs
    if len(tracks) < 5:
        return sorted(tracks, key=lambda t: (float(t.get("bpm") or 0), t.get("date", "")))
    by_bpm = sorted(tracks, key=lambda t: (float(t.get("bpm") or 0), t.get("date", "")))
    peak = by_bpm[-1]
    rest = by_bpm[:-1]
    n_after = max(1, round(len(tracks) * (1 - mashups()["sets"]["peak_at"])) - 1)
    after = sorted(rest[-2 * n_after::2], key=lambda t: -float(t.get("bpm") or 0))[:n_after]
    before = [t for t in rest if t not in after]
    climb = [before.pop(0)]
    while before:
        last = climb[-1]
        near = [t for t in before if tempo_ok(float(last.get("bpm") or 0), float(t.get("bpm") or 0))] or before[:1]
        nxt = min(near, key=lambda t: (key_distance(last.get("key"), t.get("key")), float(t.get("bpm") or 0)))
        climb.append(nxt)
        before.remove(nxt)
    return climb + [peak] + after


def for_lane(profile, lane_id: str) -> list[str]:
    """The genre ids a lane names in anchor.toml (empty for a retired lane without them)."""
    for raw in profile.raw["music"]["lanes"]:
        if raw["id"] == lane_id:
            return list(raw.get("genres") or [])
    return []


def visual(ids: list[str]) -> str:
    """The look of a song's video from its genres, base genre first."""
    gs = load()
    return "; ".join(gs[i].visual for i in ids if i in gs)


def classify(tags: str, bpm: int | None = None) -> str:
    """The active lane a song's own style prompt describes (Anchit's Suno songs, 2026-11-10: Red
    Dust Warning, hard techno with psytrance and rap verses, was filed by the day's slot instead).
    Rap decides the voice; psy, acid, rawstyle, hardstyle, phonk, groove and tempo the sound."""
    import re
    t = (tags or "").lower()
    has = lambda *ws: any(re.search(rf"(?<![a-z]){re.escape(w)}", t) for w in ws)
    rap = has("rap", "chopper", "mc ", "verses", "spitting")
    psy = has("psy", "psychedelic", "trance", "goa")
    hiphop = has("hip hop", "hip-hop", "boom bap", "trap", "808")
    if has("phonk", "cowbell"):
        return "phonktechno"
    if rap:
        if hiphop:
            return "psyhiphop" if psy else "hiphoptechno"
        if psy:
            return "psyrap"
        return "hardtechrap" if has("industrial", "hard tech", "raw", "distorted") else "raptechno"
    if has("hardstyle") and not has("rawstyle"):
        return "hardstyletechno"
    if has("rawstyle"):
        return "rawbounce"
    if psy:
        return "acidpsy" if has("acid", "303") else "psy"
    if has("hyper") or (bpm or 0) >= 185 or re.search(r"\b(1[89]\d|2\d\d)\s*bpm", t):
        return "hyper" if has("acid", "hyper", "arp") else "bounce"
    if has("groove"):
        return "hardgroove"
    if has("bounce", "bouncy"):
        return "bounce"
    return "hardtech"
