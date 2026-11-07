# ANCHOR songbook: how every song is written

Anchit, 2026-11-07: "the songs need proper theme selection and lyrics which both need to be
thought of properly and structurally and written as humans. Not every song requires a shloka,
not every song should have repeated flows. Need uniqueness, realness and logic. Choose the song
name based on theme and lyrics. Songs could be stories or revolts or just music or anything;
they have to give a certain vibe which is different for each song. Learn from Kindness Needs
Truth and Project Mayhem. Real human voices, never mechanical or robotic. Proper lyrics like
humans: emotions, feelings, bars, verses, hooks."

Every song in `artist/songbook/*.toml` is a complete song written by a person (or by Claude
writing as a songwriter), used once, never re-rolled from parts. The robot no longer assembles
lyrics from line pools.

## The bar: Kindness Needs Truth

What makes it work, and what every song here must do:

1. **One idea with tension.** Not "party" but "being kind cost me, so is kindness still right?"
   Two forces pull against each other (heart vs head, staying vs leaving, the crowd vs me).
2. **A speaker and a listener.** Someone real is talking to someone real (a friend, an ex, a
   boss, a younger self, the city, a crowd). Use I / you / we.
3. **Concrete pictures, not abstractions.** "Held the elevator, held my tongue, held a friend
   from the ledge", "drove home silent in a borrowed coat". Objects, places, small actions.
4. **The story moves.** Verse 1 sets the scene, verse 2 complicates it, the bridge turns, the
   last chorus means something new because of what came before. A listener could retell it.
5. **The hook states the thesis in plain, singable words**, and the title is the strongest
   phrase of the hook, so the name could only belong to this song.
6. **Conversational rhythm.** Lines sound said, not written. Contractions, questions, asides.
7. **Rhyme serves meaning.** Slant rhymes are fine. Never a forced rhyme or a filler line.

Project Mayhem is the other pole: a revolt, mostly music, few words, a chant that a crowd can
take over. Some songs here are like that on purpose.

## Forms (vary them; never two of the same form in a row)

- `story`: characters, a place, something happens, an ending.
- `revolt`: defiance against something specific (a rule, a boss, a town, a voice in your head).
- `argument`: two sides inside one person (the Kindness Needs Truth form).
- `confession`: something hard admitted, quietly, then loudly.
- `letter`: addressed to one person, past or future.
- `celebration`: pure joy with a reason (a win, a reunion, a first), still concrete.
- `vibe`: mostly music; a few lines, a mood, a chant. Short lyrics on purpose.
- `dialogue`: two voices, two points of view, answering each other.
- `mantra`: Sanskrit shloka or chant as the spine. Psy songs only, at most 1 in 6 psy songs,
  and only where the subject is spiritual (stillness, letting go, the self).

## Genre voices

- `hardtech` (hard bounce, rawstyle bounce, hard groove, hyper acid): sung or shouted English,
  festival scale, a hook a crowd can scream back. Verses short and punchy.
- `psy` (psychedelic, acid psy): hypnotic, inward, images of light, water, time, the body;
  whispered or half-sung verses; mantras rarely.
- `rap` (rap techno, psy rap, hard tech rap): real bars. Internal rhyme, wordplay, punchlines,
  a point of view. Can be wacky gangster swagger, hard and heavy, or storytelling. 16 bar
  verses cut to 8 to 12 lines so they fit the tempo.
- `hiphop` (hip hop techno, psy hip hop): story bars and heavy bars mixed, a sung hook.

## Shape (ACE-Step reads the section tags)

Tempo is 160 to 200 BPM and about a third of the track is instrumental drops, so lyrics are
shorter than a pop song: 16 to 34 sung lines, under 1,900 characters. Typical:

    [Intro]          1 to 2 lines, spoken or whispered
    [Verse 1]        4 to 8 lines (rap: 8 to 12)
    [Pre-Chorus]     2 lines, optional
    [Chorus]         2 to 4 lines, the title in it
    [Drop]           instrumental, or the title chanted once
    [Verse 2]        4 to 8 lines that move the story on
    [Chorus]
    [Bridge]         2 to 4 lines, the turn
    [Drop]
    [Final Chorus]   the chorus changed by what happened
    [Outro]          1 to 2 lines

Vary it: some songs open on the hook, some have no bridge, `vibe` songs are mostly drops.
Write a direction in the tag when it helps the singer, e.g. `[Verse 2: half-whispered]`,
`[Drop: crowd chants]`.

## Voices (caption line)

Each song names one real human voice the way a session singer is booked: gender, register,
texture, delivery, e.g. "raspy male baritone, close-mic, conversational, a crack on the high
notes". Never: robotic, vocoder, auto-tuned, text-to-speech, AI voice, monotone. Never two songs
in a row with the same voice.

## Never

- Robots, machines, systems, circuits, code, signals, data, neon-as-filler, "the void".
- Lines that could sit in any other song ("feel the energy", "lose control tonight").
- The same opening, the same chorus pattern, or the same rhyme sound in songs close together.
- Em or en dashes (use a hyphen or a comma).
- A title already used on the channel or that is an existing well-known song.
