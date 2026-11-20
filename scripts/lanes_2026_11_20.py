"""One-off: the genre set Anchit decided on 2026-11-20.

"ensure only the genres as asked and their mashups are created - hard techno, industrial
techno, warehouse techno, acid techno, psychadellic acid, psychadellic techno, rap hard rap -
ensure mashups have bpm higher than 180 bpm."
Run once from the repo root; it edits artist/anchor.toml and artist/genres.toml in place.
"""
import re
from pathlib import Path

G = Path("artist/genres.toml")
A = Path("artist/anchor.toml")

NEW_GENRES = '''
[[genre]]
id = "warehouse_techno"
name = "Warehouse Techno"
family = "techno"
bpm = [130, 150]
confidence = "low"
note = "a club and scene term more than a production school: the raw techno of big concrete rooms"
feel = "four-on-the-floor, straight, relentless"
kick = "big rumbling kick with a long concrete-room tail"
bass = "rumble fused with the kick, mono"
percussion = "raw claps and hats in a huge room reverb, metal hits"
synths = "raw stabs, noise, few melodies"
vocals = "rare: a shouted phrase or a spoken line in the room"
structure = "long hypnotic loops, a new layer every 8 bars, one big breakdown"
prompt = ["warehouse techno", "warehouse room reverb", "rumbling kick", "raw stabs", "concrete room"]
negative = ["bright pop chords", "funky swing", "acoustic drums"]
visual = "concrete warehouse, one white strobe, haze, a crowd in silhouette"
sources = ["https://muzeme.io/genre-guides/techno", "https://bpmcalc.com/genres/techno/"]

[[genre]]
id = "psychedelic_techno"
name = "Psychedelic Techno"
family = "techno"
bpm = [135, 175]
confidence = "low"
note = "techno with psytrance colour: trippy sequences and delays over a techno kick, not full psytrance"
feel = "four-on-the-floor, hypnotic, rolling"
kick = "punchy techno kick, rolling bass between the kicks"
bass = "rolling off-beat bass, sometimes the psy kick-bass-bass-bass roll"
percussion = "swung off-beat hats, shakers, tribal toms"
synths = "phased acid sequences, trippy delays, swirling filtered arps, new layer every 8 bars"
vocals = "whispers, half-sung lines, chants"
structure = "layers added every 4 to 8 bars up to a climax, a breakdown, then a new pattern over the bass"
prompt = ["psychedelic techno", "phased acid sequences", "trippy delays", "swirling arps", "hypnotic"]
negative = ["clean house kick", "acoustic drums", "ballad"]
visual = "kaleidoscope colour, liquid light, fractals over a crowd"
sources = ["https://en.wikipedia.org/wiki/Psychedelic_trance", "https://www.melodigging.com/genre/hypnotic-techno"]
'''

RETIRE = ["bounce", "rawbounce", "hardgroove", "hiphoptechno", "psyhiphop", "hardstyletechno", "phonktechno"]

# lane id -> fields to set (bpm as strings, the way the file writes them)
CHANGE = {
    "hardtech": dict(name="Hard Techno", genres=["hard_techno"], tempo_like=["hardtek"], bpm=["165", "175"], weight=3),
    "psy": dict(name="Psychedelic Techno", genres=["psychedelic_techno"], tempo_like=["hardtek"], bpm=["160", "170"], weight=2),
    "acidpsy": dict(name="Psychedelic Acid", genres=["psychedelic_techno", "acid_techno"], tempo_like=["hardtek"], bpm=["164", "175"], weight=3),
    "raptechno": dict(name="Hard Rap", genres=["techno_rap", "hard_techno"], bpm=["160", "170"], weight=3),
    # mashups: two decided genres, over 180 BPM
    "hyper": dict(name="Hard Acid Techno", genres=["hard_techno", "acid_techno"], tempo_like=["hardtek", "gabber"], bpm=["182", "195"], weight=2),
    "psytech": dict(name="Psychedelic Hard Techno", genres=["psychedelic_techno", "hard_techno"], tempo_like=["hitech"], bpm=["182", "192"], weight=2),
    "psyrap": dict(name="Psychedelic Hard Rap", genres=["techno_rap", "psychedelic_techno"], tempo_like=["hitech"], bpm=["181", "190"], weight=2),
    "hardtechrap": dict(name="Industrial Hard Rap", genres=["techno_rap", "industrial_techno"], tempo_like=["hardtek", "gabber"], bpm=["181", "190"], weight=2),
}


def lane_block(id, group, genres, tempo_like, name, bpm, weight, caption, textures, style_line, tags, era, groove,
               production, mood_arcs, special_moments, extra=""):
    q = lambda xs: "[" + ", ".join(f'"{x}"' for x in xs) + "]"
    return f'''[[music.lanes]]
id = "{id}"
group = "{group}"
genres = {q(genres)}
tempo_like = {q(tempo_like)}
name = "{name}"
bpm = {q(bpm)}
weight = {weight}
caption = "{caption}"
textures = {q(textures)}
genre_line = "{name}"
style_line = "{style_line}"
tags = {q(tags)}
era = "{era}"
groove = "{groove}"
production = "{production}"
mood_arcs = {q(mood_arcs)}
special_moments = {q(special_moments)}
{extra}
'''


def main():
    g = G.read_text()
    if "warehouse_techno" not in g:
        G.write_text(g.rstrip("\n") + "\n" + NEW_GENRES)

    s = A.read_text()
    head, *blocks = s.split("[[music.lanes]]")
    out = [head]
    for b in blocks:
        m = re.search(r'^id = "([^"]+)"', b, re.M)
        lid = m.group(1) if m else ""
        if lid in RETIRE and not re.search(r"^retired = true", b, re.M):
            b = b.replace(f'id = "{lid}"\n', f'id = "{lid}"\nretired = true\n', 1)
        if lid in CHANGE:
            for k, v in CHANGE[lid].items():
                val = f'"{v}"' if isinstance(v, str) else ("[" + ", ".join(f'"{x}"' for x in v) + "]" if isinstance(v, list) else str(v))
                if re.search(rf"^{k} = ", b, re.M):
                    b = re.sub(rf"^{k} = .*$", f"{k} = {val}", b, count=1, flags=re.M)
                else:
                    b = b.replace(f'id = "{lid}"\n', f'id = "{lid}"\n{k} = {val}\n', 1)
        out.append(b)
    s = "[[music.lanes]]".join(out)

    rap_extra_src = re.search(r'id = "raptechno".*?(^vocals = .*?$\n^negative = .*?$)', s, re.S | re.M).group(1)
    new = [
        lane_block("industrialtechno", "hardtech", ["industrial_techno"], ["hardtek"], "Industrial Techno", ["160", "170"], 2,
                   "industrial techno, distorted rumble kick dominant, metallic percussion, factory noise, saturation on the low end, clanking machinery, chanted hook",
                   ["clanking machinery hits", "hydraulic hiss", "steel pipe percussion", "factory siren sweeps", "grinding metal noise", "distorted kick rumble"],
                   "Industrial Techno, Hard Techno, Warehouse Techno, Driving Techno",
                   ["industrial techno", "hard techno", "industrial hard techno", "warehouse techno", "techno 2026"],
                   "Modern industrial techno, Berlin and Dutch factory sound pushed to festival speed",
                   "relentless four-on-the-floor, a distorted rumble on every off-beat, straight sixteenth hats",
                   "Loud and saturated, kick dry and up front, metal percussion wide, chants dry",
                   ["hard and focused, grinding into a full-room stomp, ending on one last hit", "heavy from the first bar, every drop harder, then a clean cut", "steady and driving, building into pure force, then the machines power down"],
                   ["the machinery hits lock to the kick for the last drop", "a factory siren that resolves only on the final drop", "one bar of pure kick rumble before the second drop"]),
        lane_block("warehouse", "hardtech", ["warehouse_techno"], ["hardtek"], "Warehouse Techno", ["160", "170"], 2,
                   "warehouse techno, big rumbling kick with a concrete room tail, raw stabs and claps in warehouse room reverb, metal hits, haze and strobes, chanted hook",
                   ["warehouse room reverb", "raw chord stabs", "metal clangs", "crowd noise swells", "snare rolls into drops", "rumble tails"],
                   "Warehouse Techno, Raw Techno, Hard Techno, Rave Techno",
                   ["warehouse techno", "raw techno", "hard techno", "rave techno", "techno 2026"],
                   "The raw techno of big concrete rooms, loud, simple and relentless",
                   "four-on-the-floor that never stops, a rumbling kick tail filling the room, claps on two and four",
                   "Big room, kick dry and huge, stabs and claps in a concrete reverb, chants close",
                   ["hypnotic and raw, the room filling up, ending in one big roar", "simple and relentless, a new layer every eight bars, then a sudden clean stop", "dark room, bright strobes, building to a hands-up drop"],
                   ["the room reverb opens wide for one bar before the second drop", "a raw stab that answers the chant", "the kick rumble swallows everything for the last two bars"]),
        lane_block("acidtechno", "psy", ["acid_techno"], ["hardtek"], "Acid Techno", ["160", "172"], 2,
                   "acid techno, squelchy 303 acid line with slides and filter sweeps, punchy distorted kick, rolling off-beat bass, rave energy, chanted hook",
                   ["rubbery acid squelches", "bouncing 303 slides", "resonance peaks", "snappy claps", "rising filter tension", "delay throws"],
                   "Acid Techno, Hard Acid, Rave Techno, Driving Techno",
                   ["acid techno", "303 acid", "hard acid techno", "rave techno", "techno 2026"],
                   "1990s acid techno rave lineage, the 303 at the centre, fast for 2020s floors",
                   "four-on-the-floor, the 303 riding sixteenths with slides, off-beat bass",
                   "303 centred and squelchy, kick punchy and dominant, chants dry",
                   ["squelching and sly, getting wilder every section, ending on a happy squeal", "driving and focused, the filter opening wider each drop", "playful acid chase, peaking in a resonant scream, then cut"],
                   ["the 303 filter opens fully only on the second drop", "a resonance peak that squeals across the last bar", "the acid line drops an octave for the final drop"]),
        lane_block("industrialacid", "hardtech", ["industrial_techno", "acid_techno"], ["hardtek", "gabber"], "Industrial Acid Techno", ["181", "190"], 2,
                   "industrial techno, acid techno, very fast distorted rumble kick, screaming 303 acid line, metallic percussion, factory noise, saturation, chanted hook",
                   ["clanking machinery hits", "screaming 303 slides", "steel pipe percussion", "grinding metal noise", "resonance peaks", "factory siren sweeps"],
                   "Industrial Acid, Hard Acid, Industrial Techno, Driving Techno",
                   ["industrial techno", "acid techno", "industrial acid", "hard techno", "techno 2026"],
                   "Industrial techno and acid techno fused at mashup speed, over 180 BPM",
                   "very fast four-on-the-floor, a distorted rumble on every off-beat, the 303 screaming in sixteenths",
                   "Loud and saturated, kick dominant, 303 centred and screaming, metal percussion wide",
                   ["hard and fast, the acid screaming louder every drop, ending on one hit", "machine-tight and frantic, building into a full-speed stomp", "relentless from the first bar, a 303 that never lets go"],
                   ["the 303 and a factory siren lock together in the final drop", "one bar of only kick and acid before the second drop", "the acid line climbs an octave into the last drop"]),
        lane_block("warehouseacid", "psy", ["warehouse_techno", "acid_techno"], ["hardtek", "gabber"], "Warehouse Acid Techno", ["181", "190"], 2,
                   "warehouse techno, acid techno, very fast big rumbling kick, squelchy 303 acid line in warehouse room reverb, raw stabs, rave energy, chanted hook",
                   ["warehouse room reverb", "bouncing 303 slides", "raw chord stabs", "snappy claps", "rising filter tension", "crowd noise swells"],
                   "Warehouse Acid, Acid Techno, Warehouse Techno, Rave Techno",
                   ["warehouse techno", "acid techno", "warehouse acid", "rave techno", "techno 2026"],
                   "Warehouse techno and acid techno fused at mashup speed, over 180 BPM",
                   "very fast four-on-the-floor, a rumbling kick tail, the 303 riding sixteenths with slides",
                   "Big room, kick huge and dry, 303 centred, stabs and claps in a concrete reverb",
                   ["raw and fast, the 303 getting wilder in a giant room, ending in a roar", "hypnotic acid loop that keeps opening up, then a clean cut", "fast and euphoric, every drop bigger than the last"],
                   ["the 303 filter opens fully only on the second drop", "the room reverb swallows the acid for one bar", "a raw stab answers the chant in the final drop"]),
        lane_block("acidrap", "rap", ["techno_rap", "acid_techno"], ["hardtek", "gabber"], "Acid Hard Rap", ["181", "190"], 2,
                   "fast rap over acid techno, rap over hard techno under every verse, very fast distorted kick, squelchy 303 acid line, rumbling sub on the off-beat, chanted hook",
                   ["squelching 303 lines", "vocal ad-lib echoes", "snare rolls into hooks", "resonance peaks", "scratch fills", "distorted kick rumble"],
                   "Acid Rap, Hard Rap, Acid Techno, Rave Rap",
                   ["acid techno", "rap techno", "hard rap", "techno rap", "techno 2026"],
                   "Hard rap riding acid techno at mashup speed, over 180 BPM, the kick never leaves",
                   "very fast four-on-the-floor under verses and drops alike, the 303 bouncing between the kicks, the rap in double time",
                   "Loud and saturated, rap vocal dry and centred, 303 squelching around it, kick dominant",
                   ["fast and hungry, every verse harder, ending on one shout", "grinning swagger over a screaming 303, exploding into the hook", "relentless bars, a hook the crowd screams back, then a hard stop"],
                   ["the 303 rises under the last rap line, then everything slams back", "the rapper doubles the flow for one bar", "the crowd chant answers the rapper in the final drop"],
                   extra="voice = \"rap\"\n" + rap_extra_src),
    ]
    marker = "# Retired lanes (2026-10-04)"
    assert marker in s
    if 'id = "warehouse"' not in s:
        s = s.replace(marker, "\n".join(new) + "\n" + marker, 1)
    s = re.sub(r'^slot_groups = .*$', 'slot_groups = ["hardtech", "rap", "psy", "any"]', s, count=1, flags=re.M)
    A.write_text(s)


if __name__ == "__main__":
    main()
