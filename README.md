# ANCHOR autopilot

A robot that releases one **industrial hard techno** track a day for [ANCHOR](https://www.youtube.com/@AT_ANCHOR):
it writes the brief, generates the music, masters it, designs the cover, renders a YouTube Short, publishes it
with YouTube's AI-use disclosure, and updates **[anchor.anchit-tandon.com](https://anchor.anchit-tandon.com)**.
It costs nothing to run.

```
15:07 UTC  GitHub Actions cron ─┐
                                ├─ brief      artist/anchor.toml + catalog history (no repeats)
                                ├─ music      ACE-Step 1.5 turbo via acestep.cpp, CPU only (MIT licence)
                                ├─ QC         duration, silence, dropouts, low end, tempo; 1 retry
                                ├─ master     gain + limiter to -14 LUFS / -1.5 dBTP → FLAC + MP3
                                ├─ cover      Cloudflare Workers AI FLUX.1 schnell (free) → procedural fallback
                                ├─ Short      45 s of the strongest bars, 1080x1920, 6 rotating visual families
                                ├─ release    GitHub Release (MP3, FLAC, Short, cover)
                                ├─ media host GitHub Pages (direct MP4 URL for Buffer)
                                ├─ YouTube    Buffer API → public Short at 17:30 UTC, isAiGenerated = true
                                └─ website    catalog commit → Vercel deploy → anchor.anchit-tandon.com
```

## One-time setup

From a Mac with `git` and the GitHub CLI (`gh`) logged in, `./scripts/publish_to_github.sh` does steps 1-2
(creates the repo, pushes, switches Pages on) and starts a render-only rehearsal.

| # | What | Where | Needed for |
|---|------|-------|-----------|
| 1 | Public repo `Anchit-AI-Hustle/anchor-autopilot` with this code | GitHub | everything |
| 2 | Pages source = **GitHub Actions** | repo Settings → Pages | media host |
| 3 | Vercel project linked to the repo, root directory `site`, domain `anchor.anchit-tandon.com` | Vercel | website |
| 4 | Secret `BUFFER_API_KEY` (Buffer free plan, YouTube channel @AT_ANCHOR connected) | repo Settings → Secrets → Actions | YouTube publishing |
| 5 | Optional: secrets `CF_ACCOUNT_ID` + `CF_API_TOKEN` (Workers AI, free) | same | AI cover art |

Without `BUFFER_API_KEY` the robot still releases every day on the website and GitHub (status `released`);
YouTube publishing switches on as soon as the key is added. Without the Cloudflare secrets it draws its own
procedural covers.

## Operating it

- **Run now:** Actions → *Daily drop* → *Run workflow* (options: `date`, `publish_now`, `dry_run`).
- **Rehearse safely:** run with `dry_run` ticked; it renders and uploads the files as a workflow artifact only.
- **Steer the sound and look:** edit `artist/anchor.toml` (lanes, BPM ranges, captions, title words, colours, post time).
- **Failures:** GitHub emails you, the status panel on the website turns red, and the next day runs normally.
  A re-run for a date that already published is skipped, so nothing double-posts.

## Local use

```bash
pip install -r requirements.txt -r requirements-dev.txt   # plus ffmpeg on PATH
python -m anchor plan                                      # today's brief
python -m anchor make --engine fixture --art procedural    # full drop with a synthetic test track
python -m pytest -q
```

Real generation needs acestep.cpp and the GGUF models (see `.github/workflows/daily.yml`), then
`ACESTEP_BIN=... ACESTEP_MODELS=... python -m anchor make`.

## Limits worth knowing

- Generation runs on a free 4-vCPU GitHub runner: about 25-40 minutes a day, well inside the 6-hour job limit.
- YouTube's monetisation rules penalise templated mass production. Every drop varies the sound lane, key, tempo,
  cover and visual family, and the AI disclosure is always on. Keep an eye on quality rather than quantity.
- Buffer's free plan allows 10 scheduled posts per channel and 250 API calls a day; the robot uses a handful.

## Engine and cadence (v2)

- **Music engine:** `[music] engine = "lyria"` - Google Lyria 3.5 through the Gemini API
  (`GEMINI_API_KEY` secret). `fallback_engine = "acestep_cpp"` runs when Lyria is unavailable.
  There is no official Suno API; the Suno web app is never automated.
- **Cadence:** `[schedule] every_days = 1`: one record every day. The cron fires at 13:07 UTC
  and the posts go live at 17:30 UTC; the four hours cover the CPU fallback engine and one
  retry. `every_days = 2` with `anchor_date` makes it every second day
  (`python -m anchor cadence --date YYYY-MM-DD` answers yes/no; a manual `workflow_dispatch`
  always runs).
- **Three posts a day from one record:** the full 16:9 track to YouTube as a video, the
  strongest 45 s to YouTube as a Short (the preview: shorter words, a pointer to the full
  track, #shorts, no second subscriber notification), and the full 9:16 to Instagram as a
  Reel, all in the same slot. The full track needs the channel's own credentials (`YT_*`,
  below): Buffer publishes YouTube Shorts only, so without them the Short and the Reel go
  out through Buffer and the full track waits on the site and in the release, marked
  "needs youtube credentials" rather than failing the run. `sync` follows the full track
  and the Short separately; the ledger shows both.
- **Every record is its own record:** the day draws the lane, key, tempo, textures, mood,
  special moment, the length (`duration_range_s`, 135-170 s) and the arrangement shape
  (`music.SHAPES`: classic, early, peak, twice), so no two days share a timeline.
- **Reach (2026-09-23):** every breakout video in this niche from a channel under 6k
  subscribers is a 30 to 70 minute mix with a keyword-led title, and a bare track name scores
  62 against 70 with the genre phrase (vidIQ). So: titles are `Track | Industrial Hard
  Techno 154 BPM | ANCHOR`; the first description line is the search line; every Sunday
  `weekly-mix.yml` builds the week's drops into one continuous set (tempo order, -14 LUFS,
  eight-bar crossfades, chapters) with a moving 16:9, and the first Sunday of a month adds
  the month's set. `python -m anchor mix --period week|month`.
- **Uploading with the channel's own credentials:** set `YT_CLIENT_ID`, `YT_CLIENT_SECRET`
  and `YT_REFRESH_TOKEN` (one-time: create an OAuth desktop client in Google Cloud with the
  YouTube Data API enabled, run `python -m anchor youtube-auth --client-id ... --client-secret ...`
  on your own machine, paste the printed refresh token into the repository secrets). The
  robot then uploads from disk with tags, category, AI disclosure, scheduled publish time,
  custom thumbnail and playlist, and the Short links its full track by id. Without them,
  Buffer carries the Short only (it cannot post long-form videos). Instagram always goes
  through Buffer.
- **The back catalogue keeps up:** `retitle.yml` (every Monday, or on demand) reads every
  upload on the channel and rewrites any title or description that is not in the search-led
  form, robot drops from the catalog and the hand uploads from `site/data/channel.json`.
  Idempotent: a clean channel costs one read. `python -m anchor retitle --dry-run` shows
  what would change.
- **Your Suno songs go out first, on their own:** there is no official Suno API (checked
  2026-09-23) and the third-party "Suno APIs" drive accounts through the web app against
  Suno's terms, so the robot never generates on Suno. Instead, every day before it renders,
  it reads your public Suno profile and queues the best song that is on format, above
  `[queue] min_rating`, not another take of a song already out, and not personal
  (`never_words`: birthday, family, love and so on in the title or prompt; `never_titles`
  for exact titles). Lyria renders only on a day the queue is empty. `python -m anchor
  queue-plan` shows every song's verdict and reason; `queue-add --force` releases a held
  take anyway (the audio gate still runs).
- **Craft, learned from the channel (`anchor/craft.py`):** the 2026-09-23 rating of all 21
  videos found the weakest records share three faults: almost all their energy below 60 Hz
  (silent on a phone), a near-mono image, and no breakdown. So a generated take must have a
  breakdown of 8 s or more at least 8 dB under the peak and a sound that moves, or it is
  regenerated while seeds remain (the last take ships with a warning rather than miss the
  day); every record, your Suno songs included, then gets the finishing pass: the sub a
  little lower with its harmonics where a phone plays them, the kick's click and air lifted,
  wider above 250 Hz, mono below, and only as much as it needs. The prompt asks for the same
  things up front (`[music] mastering`, the breakdown direction). The ledger shows each
  record's craft numbers before and after.
- **One version of each record everywhere (`anchor/versions.py`):** `site/data/versions.json`
  names each record whose site player, download, Short and YouTube video should all carry one
  new master, where to build it from (the release master, the original Suno render, or two
  takes welded) and what to do to it: `extend` (a 16-bar breakdown made from the record and
  its drop phrase played twice, on its own 8-bar phrases), `tame` (turns down the noise wash
  Suno leaves over breakdowns, the "distortion" in them, leaving tonal highs and everything
  under 6 kHz alone) and `finish` (the craft pass). `versions.yml` runs on every change to
  that file: it builds each pending entry, keeps the first master in the release as
  `<name>-original.*`, replaces the release files under their old names with a `?v=` mark on
  the site links so no cache plays the old one, and, with the `YT_*` secrets, uploads the new
  video and Short with the old ones' words and sets the old ones to private. Nothing is ever
  deleted, a rebuild always starts from the kept original, and a run that stops halfway
  resumes where it stopped. The new uploads start from zero views; that is YouTube's rule
  (a video's audio cannot be swapped in place). `python -m anchor versions build --only
  YYYY-MM-DD` builds one locally into `build/versions/`.
- **Title:** the most repeated sung phrase becomes the title when it reads as one and is unused.
- **Uniqueness gates:** cover art must be >= 84 hash-distance from every released cover; the
  audio is printed twice against every released master, loudness envelope (limit 0.80) and
  spectral sequence, 24 bands every 0.5 s (limit 0.75). The 2026-09-23 audit of the 15
  released masters: highest envelope 0.48, highest sequence 0.65, nothing near either limit.
  A take over a limit is regenerated with the next seed, then the run fails loudly.
- **Outputs per drop:** full 16:9 video (YouTube, first frame = thumbnail), full 9:16 (Instagram Reel),
  45 s Short (YouTube), MP3/FLAC, cover.

## The ledger (/ops/)

`site/data/ledger.json` is the tracker behind `anchor.anchit-tandon.com/ops/` (not indexed,
not linked). `anchor record` writes one entry per drop: every attempt the engine made (seed,
QC result, nearest released record), the Suno siblings of a queued track and which one was
picked, every cover draw and how close it came to an existing one, every file rendered, every
upload target with its status and link, and a decision table: each published field, the rule
that produced it, and the evidence. `anchor sync` refreshes the upload rows when Buffer reports
a status or a link; `anchor ledger` does the same by hand; `anchor check` validates the file.
The page reads the ledger, the catalog and the status file, so it is current as soon as the
drop commit deploys. Songs released by hand before the ledger existed were backfilled on
2026-09-20 with `source: "manual"` and are never touched by the robot.

## The words (v6: the vibe, hyped, short)

The YouTube title is the track's name and nothing else. The description is the vibe and the
theme of the record in two to four sentences that build like an intro: what it feels like,
what it's about, where it takes you. Nothing mechanical: no timestamps, no tempo in the body,
no section names. Then a five-line footer: genre · BPM · artist, the playlist, the site and
Instagram on one line, the AI disclosure, © and three hashtags. About 400 characters in all,
no em dashes anywhere. `anchor/copy.py` asks Gemini (`GEMINI_API_KEY`, model
`gemini-2.5-flash`) for the body from the brief's mood, theme and textures and rejects any
answer with a clock time, a section name, a marketing word, an exclamation mark or a dash;
with no key (or `ANCHOR_COPY=template`) a seeded template writes it from the same brief. The
38 videos on the channel, the playlists and the channel About were rewritten by hand in this
voice on 2026-09-21; the thumbnails were redrawn for the phone the same day
(`video.frame_169`), and full videos now render with a moving waveform
(`video.render_motion`).

