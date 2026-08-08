# Kidify Daily Video Pipeline

Fully automated daily video pipeline for the Kid-ify YouTube channel.
YouTube only — no TikTok cross-posting.

## How it works

Every day (via GitHub Actions cron), the pipeline runs four steps in order:

1. **`generate_script.py`** — Claude writes a scene-by-scene script,
   alternating between the two proven Kidify formats: guessing/reveal
   games and original brainrot-style character skits.
2. **`generate_clips.py`** — Each scene's visual description is sent to
   Kling AI, which generates a real moving video clip (not a static
   image) for that scene.
3. **`assemble_video.py`** — JSON2Video stitches the clips together,
   adds voiceover narration, burned-in captions, background music, and
   renders the final vertical short.
4. **`upload_youtube.py`** — Uploads the finished video to the Kid-ify
   channel as a public Short, marked as made-for-kids.

## Required secrets (already set in this repo)

- `ANTHROPIC_API_KEY`
- `KLING_API_KEY`
- `JSON2VIDEO_API_KEY`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`

## Running manually

Go to the Actions tab → "Daily Video Pipeline" → "Run workflow" to
trigger a run outside the daily schedule (useful for testing).

## Common failure: insufficient Kling credits

If `generate_clips.py` fails with an error containing "insufficient
balance," it means your Kling account ran out of credits. Top up at
kling.ai, then re-run the workflow manually from the Actions tab — no
code changes needed.

## Changing the posting time

Edit the `cron` line in `.github/workflows/daily-pipeline.yml`. Times
are in UTC.

## Cost per video (approximate)

- Kling clips: ~$2.50–$4.50 depending on scene count/length
- JSON2Video render: pennies
- Claude script generation: pennies
