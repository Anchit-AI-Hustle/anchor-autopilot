# How a mashup over 180 BPM moves a body

Anchit, 2026-11-21: "the mashup must be created after understanding the beats and syncing of the
two genres before mashing them up - understand the complete bpm synergising with the human body's
different body parts response to bpms". This is the rhythm every mashup lane in
`artist/lanes.toml` is built on. Tests: `tests/test_mashup_rhythm.py`.

## What the body does with tempo (sources below)

| Level | At 184 BPM | Body | Why |
|---|---|---|---|
| Kick, every beat | 184 BPM, 3.1 Hz | feet: steps, stomps | running cadence is 130 to 200 steps a minute and runners lock to the beat (Van Dyck 2015) |
| Half-time, every 2nd kick | 92 BPM, 1.5 Hz | head nod, chest and knee bounce | people prefer beats of 1.5 to 2.5 Hz (400 to 700 ms), the pace of walking (Su 2016); at fast tempi movement moves up to the slower metrical levels (Burger 2014) |
| Bar, every 4th kick | 46 BPM, 0.8 Hz | arms, hips, side-to-side sway | sway (mediolateral) locks to the bar level, bounce (vertical) to the beat (Burger 2014) |
| Off-beat eighths | between the kicks | hips and shoulders bounce | the bass bounce between the kicks |
| Sixteenths at 184 | 12 notes a second | heard as a buzz, not a rhythm | keep them for hats in builds and for texture, never for the acid line or the bass |

Heart and breath: faster tempo and simpler rhythm raise breathing, heart rate and blood
pressure; a pause drops them below where they started (Bernardi 2006). So a drop lifts the body
and a breakdown lets it recover, and the next drop lands harder after the recovery.

## The rules every mashup follows

1. One tempo, one grid. Both genres play on the same kick; nothing runs at its home tempo.
2. The techno side owns the floor: the kick on every beat (feet) and the bass bouncing on every
   off-beat (hips).
3. A half-time backbone: claps (or a metal hit) on two and four, so the head nods at 92. In a rap
   mashup these claps are the rap's own backbeat, the snare a 92 BPM hip hop beat has.
4. The second genre owns the top, slowed to fit the body: the 303 in eighth notes with sixteenth
   slides and accents (not straight sixteenths); psychedelic sequences in eighth-note triplets
   swirling against the straight kick; never the psytrance kick-bass-bass-bass sixteenth roll at
   this speed.
5. One phrase per bar: the acid or sequence turns once a bar, so arms and hips sway with it.
6. The rap rides the half-time pocket: one lyric line per half-time bar (`flow` in lanes.toml).
7. Breakdowns fall to the half-time and bar pulse (the recovery); builds roll the snare up from
   eighths to sixteenths; the drop brings every level back at once.

## Sources

- Van Dyck et al. 2015, Spontaneous Entrainment of Running Cadence to Music Tempo, Sports
  Medicine Open: https://pmc.ncbi.nlm.nih.gov/articles/PMC4526248/
- Burger et al. 2014, Hunting for the beat in the body, Frontiers in Human Neuroscience:
  https://www.frontiersin.org/journals/human-neuroscience/articles/10.3389/fnhum.2014.00903/full
- Su 2016, Visual tuning and metrical perception of realistic point-light dance movements,
  Scientific Reports: https://www.nature.com/articles/srep22774
- Bernardi, Porta, Sleight 2006, Cardiovascular, cerebrovascular, and respiratory changes induced
  by different types of music, Heart: https://pmc.ncbi.nlm.nih.gov/articles/PMC1860846/
