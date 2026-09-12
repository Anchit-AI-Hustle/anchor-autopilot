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
