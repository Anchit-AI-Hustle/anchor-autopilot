"""Load the artist profile (artist/anchor.toml) and runtime settings."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "artist" / "anchor.toml"
FONTS = ROOT / "assets" / "fonts"
SITE = ROOT / "site"
CATALOG_PATH = SITE / "data" / "catalog.json"
STATUS_PATH = SITE / "data" / "status.json"


@dataclass(frozen=True)
class Lane:
    id: str
    name: str
    bpm: tuple[int, int]
    weight: int
    caption: str
    textures: tuple[str, ...]
    genre_line: str
    style_line: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class Family:
    id: str
    name: str
    bg: str
    accent: str
    accent2: str
    viz: str
    prompt: str


@dataclass(frozen=True)
class Profile:
    raw: dict
    lanes: tuple[Lane, ...] = field(default_factory=tuple)
    families: tuple[Family, ...] = field(default_factory=tuple)

    # convenience accessors -------------------------------------------------
    @property
    def artist(self) -> dict:
        return self.raw["artist"]

    @property
    def music(self) -> dict:
        return self.raw["music"]

    @property
    def titles(self) -> dict:
        return self.raw["titles"]

    @property
    def youtube(self) -> dict:
        return self.raw["youtube"]

    @property
    def schedule(self) -> dict:
        return self.raw["schedule"]

    def lane(self, lane_id: str) -> Lane:
        for lane in self.lanes:
            if lane.id == lane_id:
                return lane
        raise KeyError(f"unknown lane {lane_id!r}")

    def family(self, family_id: str) -> Family:
        for fam in self.families:
            if fam.id == family_id:
                return fam
        raise KeyError(f"unknown visual family {family_id!r}")


def load_profile(path: Path | str = PROFILE_PATH) -> Profile:
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    lanes = tuple(
        Lane(
            id=l["id"], name=l["name"], bpm=(int(l["bpm"][0]), int(l["bpm"][1])),
            weight=int(l.get("weight", 1)), caption=l["caption"],
            textures=tuple(l.get("textures", [])), genre_line=l["genre_line"],
            style_line=l["style_line"], tags=tuple(l.get("tags", [])),
        )
        for l in raw["music"]["lanes"]
    )
    families = tuple(
        Family(id=f["id"], name=f["name"], bg=f["bg"], accent=f["accent"],
               accent2=f["accent2"], viz=f["viz"], prompt=f["prompt"])
        for f in raw["visual"]["families"]
    )
    validate(raw, lanes, families)
    return Profile(raw=raw, lanes=lanes, families=families)


def validate(raw: dict, lanes: tuple[Lane, ...], families: tuple[Family, ...]) -> None:
    """Fail fast on a broken profile instead of producing a broken drop."""
    problems = []
    if not lanes:
        problems.append("music.lanes is empty")
    if len(families) < 4:
        problems.append("visual.families needs at least 4 entries for rotation")
    for lane in lanes:
        lo, hi = lane.bpm
        if not (60 <= lo <= hi <= 200):
            problems.append(f"lane {lane.id}: bpm range {lane.bpm} outside 60-200")
        if lane.weight < 1:
            problems.append(f"lane {lane.id}: weight must be >= 1")
    for fam in families:
        if fam.viz not in {"bars", "line", "wave", "scope"}:
            problems.append(f"family {fam.id}: viz {fam.viz!r} not supported")
        for colour in (fam.bg, fam.accent, fam.accent2):
            if not (len(colour) == 7 and colour.startswith("#")):
                problems.append(f"family {fam.id}: colour {colour!r} must be #rrggbb")
    music = raw["music"]
    if not (10 <= int(music["duration_s"]) <= 600):
        problems.append("music.duration_s must be 10-600")
    if not (15 <= int(music["short_s"]) <= 175):
        problems.append("music.short_s must be 15-175 (YouTube Shorts max 3 min)")
    if int(music["short_s"]) > int(music["duration_s"]):
        problems.append("music.short_s cannot exceed duration_s")
    hh, _, mm = raw["schedule"]["post_time_utc"].partition(":")
    if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) < 24 and 0 <= int(mm) < 60):
        problems.append("schedule.post_time_utc must be HH:MM")
    if problems:
        raise ValueError("artist profile invalid:\n- " + "\n- ".join(problems))


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value if value not in ("", None) else default
