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
                                ├─ master     gain + limiter to -10 LUFS / -1 dBTP → FLAC + MP3
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

- Generation runs on a free 4-vCPU GitHub runner: about 25–40 minutes a day, well inside the 6-hour job limit.
- YouTube's monetisation rules penalise templated mass production. Every drop varies the sound lane, key, tempo,
  cover and visual family, and the AI disclosure is always on. Keep an eye on quality rather than quantity.
- Buffer's free plan allows 10 scheduled posts per channel and 250 API calls a day; the robot uses a handful.

## Engine and cadence (v2)

- **Music engine:** `[music] engine = "lyria"` - Google Lyria 3.5 through the Gemini API
  (`GEMINI_API_KEY` secret). `fallback_engine = "acestep_cpp"` runs when Lyria is unavailable.
  There is no official Suno API; the Suno web app is never automated.
- **Cadence:** `[schedule] every_days = 2`, `anchor_date = "2026-09-20"`. The cron still fires
  daily; `python -m anchor cadence --date YYYY-MM-DD` answers yes/no and the workflow skips
  off-days. A manual `workflow_dispatch` always runs.
- **Title:** the most repeated sung phrase becomes the title when it reads as one and is unused.
- **Uniqueness gates:** cover art must be >= 84 hash-distance from every released cover;
  audio envelope similarity to any released track must be <= 0.80. Both are retried, then fail loudly.
- **Outputs per drop:** full 16:9 video (YouTube, first frame = thumbnail), full 9:16 (Instagram Reel),
  45 s Short, MP3/FLAC, cover. Publishing goes through Buffer to YouTube and Instagram
  (`BUFFER_INSTAGRAM_CHANNEL_ID`).

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

## The words (v5: short)

A phone shows about 50 characters of a title and two lines of a description, so that is the
budget. The YouTube title is the track's name and nothing else: YouTube prints the channel
name under it, and the description carries the genre and the tempo where search still finds
them. The description is three short lines, first person: what the track does, the timestamps
that matter (measured on the master, `audio.arc`), a question; then a tight footer: genre ·
BPM · artist, the playlist, the site and Instagram on one line, the AI disclosure, © and three
hashtags. About 400 characters in all. No em dashes anywhere; a hyphen or a full stop instead.
`anchor/copy.py` asks Gemini (`GEMINI_API_KEY`, model `gemini-2.5-flash`) for the three parts
and rejects any answer that uses a timestamp the record does not have, runs long, or uses
marketing words or exclamation marks; with no key (or `ANCHOR_COPY=template`) a seeded template
writes the same parts from the arc. The 38 videos on the channel, the playlists and the channel
About were rewritten by hand in this voice on 2026-09-21; the thumbnails were redrawn for the
phone the same day (`video.frame_169`), and full videos now render with a moving waveform
(`video.render_motion`).

