# Kidify Daily Video Pipeline

Fully automated daily video pipeline for the Kid-ify YouTube channel.
YouTube only — no TikTok cross-posting.

## How it works

Every day (via GitHub Actions cron), the pipeline runs four steps in order:

1. **`generate_script.py`** — Claude writes a scene-by-scene script,
   alternating between the two proven Kidify formats: guessing/reveal
   games and original brainrot-style character skits.
2. **`generate_clips.py`** — Each scene's visual description is sent to
   Wan 2.6 (via fal.ai), which generates a real moving video clip (not
   a static image) for that scene.
3. **`assemble_video.py`** — JSON2Video stitches the clips together,
   adds voiceover narration, burned-in captions, background music, and
   renders the final vertical short.
4. **`upload_youtube.py`** — Uploads the finished video to the Kid-ify
   channel as a public Short, marked as made-for-kids.

## Required secrets (already set in this repo)

- `ANTHROPIC_API_KEY`
- `FAL_API_KEY`
- `JSON2VIDEO_API_KEY`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`

## Running manually

Go to the Actions tab → "Daily Video Pipeline" → "Run workflow" to
trigger a run outside the daily schedule (useful for testing).

## Checkpoint / resume system (protects your fal.ai credits)

Right after clips are generated, the workflow commits them into a
`pending_video/` folder in this repo before attempting assembly or
upload. If either of those later steps fails, the clips aren't lost —
the *next* run detects `pending_video/` and resumes straight from
assembly, skipping script + clip generation entirely (no wasted
credits). Once a video uploads successfully, `pending_video/` is
automatically cleared so the next scheduled run starts fresh.

If you ever want to manually discard a stuck pending video (e.g. you
decided you don't want that particular one after all), just delete the
`pending_video/` folder from the repo yourself and commit - the next
run will generate a brand new video from scratch.

## Common failure: insufficient fal.ai credits

If `generate_clips.py` fails with an error containing "insufficient
balance," it means your fal.ai account ran out of credits. Top up at
fal.ai/dashboard/billing, then re-run the workflow manually from the
Actions tab — no code changes needed.

## Changing the posting time

Edit the `cron` line in `.github/workflows/daily-pipeline.yml`. Times
are in UTC.

## Cost per video (approximate)

- Wan 2.6 clips: ~$1.25–$2.50 depending on scene count/length
- JSON2Video render: pennies
- Claude script generation: pennies
