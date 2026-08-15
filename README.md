# Kidify Daily Video Pipeline

Fully automated daily video pipeline for the Kid-ify YouTube channel.
YouTube only — no TikTok cross-posting.

## How it works

Every day (via GitHub Actions cron), the pipeline runs four steps in order:

1. **`generate_script.py`** — Claude writes a scene-by-scene script,
   rotating across five formats: guessing/reveal games, brainrot-style
   character skits, original superhero stories, original cartoon
   adventures, and vehicle-vs-obstacle. Two of these formats
   (guessing/reveal, vehicle-vs-obstacle) are marked as "image" type;
   the other three ("video" type) need custom AI-generated characters.
2. **`generate_visuals.py`** — For "video" type scripts, sends each
   scene to Wan 2.6 (via fal.ai) for a real moving AI-generated clip.
   For "image" type scripts, searches Pexels (free) for a matching
   stock photo instead - no AI generation cost for these formats.
3. **`assemble_video.py`** — JSON2Video stitches everything together:
   video clips play as-is; images get a slow pan/zoom (Ken Burns)
   effect so they don't feel static. Adds voiceover narration and
   burned-in captions, renders the final vertical short.
4. **`upload_youtube.py`** — Uploads the finished video to the Kid-ify
   channel as a public Short, marked as made-for-kids.

## Required secrets (already set in this repo)

- `ANTHROPIC_API_KEY`
- `FAL_API_KEY` (used only for the 3 AI-video formats)
- `PEXELS_API_KEY` (free - used only for the 2 stock-image formats)
- `JSON2VIDEO_API_KEY`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`

## Running manually

Go to the Actions tab → "Daily Video Pipeline" → "Run workflow" to
trigger a run outside the daily schedule (useful for testing).

## Checkpoint / resume system (protects your fal.ai credits)

After EVERY successfully generated clip (not just at the end), progress
is saved. If the run then fails for any reason - out of credits, a
network blip, JSON2Video or YouTube erroring - the workflow still
commits whatever clips were generated into a `pending_video/` folder
in this repo before ending.

On the *next* run, it loads that pending state and **only generates
the clips that are still missing** - already-generated clips are
never re-paid-for or regenerated. Once all clips exist, it proceeds to
assembly and upload automatically. Once upload succeeds, `pending_video/`
is cleared so the next scheduled run starts a brand new video.

If clip generation is still incomplete (e.g. you haven't topped up
credits yet), the workflow simply stops cleanly after checkpointing -
no error spam, it'll just pick up again on the next scheduled run (or
you can trigger it manually once you've topped up).

To manually discard a stuck pending video, delete the `pending_video/`
folder from the repo and commit - the next run starts fresh.

## Common failure: insufficient fal.ai credits

If `generate_clips.py` fails with an error containing "insufficient
balance," it means your fal.ai account ran out of credits. Top up at
fal.ai/dashboard/billing, then re-run the workflow manually from the
Actions tab — no code changes needed.

## Changing the posting time

Edit the `cron` line in `.github/workflows/daily-pipeline.yml`. Times
are in UTC.

## Cost per video (approximate)

- **Image-format videos** (guessing/reveal, vehicle-vs-obstacle): only
  Claude script generation + JSON2Video render, both pennies. No AI
  video generation cost at all.
- **Video-format videos** (brainrot, superhero, cartoon adventure):
  Wan 2.6 clips ~$1.25–$2.50 depending on scene count/length, plus
  pennies for script + render.

Since formats rotate randomly across 5 options (2 free, 3 paid), you'll
see roughly 40% of videos cost near-zero and 60% cost the AI-video rate
- averaging out to noticeably less than if every video used AI clips.
