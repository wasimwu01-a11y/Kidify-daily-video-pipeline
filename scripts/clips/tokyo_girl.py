"""
Placements - "GTA 6 Clipping Campaign - Tokyo Girl" (TikTok / Instagram only).

Makes one ~12 s SILENT vertical GTA 6 edit a day from official Rockstar
footage in assets/gta6/ (trailer clips .mp4 and screenshots .jpg/.png),
tells a mini story with on-screen text, and emails it with a ready caption.

Silent on purpose: the campaign only pays when the OFFICIAL "Tokyo Girl"
sound is added inside the TikTok/Instagram app, and it bans talking,
voiceovers, game dialogue and trailer music. You add the sound when posting.
"""

import os
import sys
import glob
import json
import random

sys.path.insert(0, os.path.dirname(__file__))
from common import (  # noqa: E402
    OUTPUT_DIR, load_state, save_state, ask_claude_json, strip_emoji,
    write_ass, ffmpeg_filter_path, run, send_email, EMAIL_SAFE_BYTES,
)

ASSET_DIR = os.environ.get("GTA6_ASSET_DIR", "assets/gta6")
SEGMENTS = 3
SEG_SECONDS = 4.0
TIKTOK_CREDIT = "Song: Tokyo Girl by @Passive"
IG_CREDIT = "Song: Tokyo Girl by @PassiveBand"

THEMES = [
    "GTA 6 news, trailer details, theories or rumors (on-screen text tells the story)",
    "GTA 6 memes and hype: waiting for the game, launch-day plans, relatable fan jokes",
    "Jason & Lucia relationship memes: couple jokes, partners in crime, annoying your partner",
    "GTA 6 edits and Vice City views: cars, driving, sunsets, beaches, city at night",
]

SYSTEM = """You write on-screen text for silent 12-second GTA 6 TikToks.
The video has NO voice - the song "Tokyo Girl" plays over it - so the text
must carry the whole joke or story in 3 short beats (one per 4-second shot).

Rules:
- Each beat max 45 characters, punchy, readable in 2 seconds. English.
- Beat 1 is the hook. Beat 3 is the payoff / punchline.
- No emoji, no hashtags inside the beats, no real brand names besides GTA/Rockstar.
- Never present a rumor as confirmed fact - say "rumor" / "theory".
- Don't repeat recent ideas (given below).
Return ONLY JSON:
{"theme": "...", "beats": ["...", "...", "..."],
 "caption": "short TikTok caption with 3-5 hashtags (no song credit, I add it)"}"""


def list_assets():
    vids = sorted(glob.glob(os.path.join(ASSET_DIR, "**", "*.mp4"), recursive=True))
    imgs = sorted(sum((glob.glob(os.path.join(ASSET_DIR, "**", ext), recursive=True)
                       for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp")), []))
    return vids, imgs


def media_duration(path: str) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", path]).stdout.strip()
    return float(out or 0)


def make_segment(src: str, is_video: bool, out: str):
    fit = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
           "setsar=1,fps=30,format=yuv420p")
    if is_video:
        dur = media_duration(src)
        start = random.uniform(0, max(dur - SEG_SECONDS - 0.5, 0))
        cmd = ["ffmpeg", "-y", "-nostdin", "-ss", f"{start:.2f}", "-i", src,
               "-t", str(SEG_SECONDS), "-an", "-vf", fit]
    else:
        frames = int(SEG_SECONDS * 30)
        zoom = (f"scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,"
                f"zoompan=z='min(zoom+0.0012,1.2)':d={frames}:s=1080x1920:fps=30,"
                "setsar=1,format=yuv420p")
        cmd = ["ffmpeg", "-y", "-nostdin", "-loop", "1", "-i", src,
               "-t", str(SEG_SECONDS), "-vf", zoom]
    run(cmd + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out])


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    vids, imgs = list_assets()
    if not vids and not imgs:
        send_email("[Tokyo Girl] No GTA 6 footage yet",
                   f"Add official trailer clips (.mp4) and screenshots (.jpg/.png) to "
                   f"{ASSET_DIR}/ in the repo (from rockstargames.com/VI/media). "
                   "After launch, add your own gameplay recordings there too.")
        return

    state = load_state()
    history = state.get("tokyo_girl_history", [])[-20:]
    theme = THEMES[len(state.get("tokyo_girl_history", [])) % len(THEMES)]
    script = ask_claude_json(
        SYSTEM,
        f"Theme for today: {theme}\nRecent ideas to avoid: {json.dumps(history)}",
        max_tokens=800,
    )
    beats = [strip_emoji(b)[:50] for b in script["beats"][:SEGMENTS]]

    # pick footage: prefer video clips, mix in screenshots
    pool = [(v, True) for v in vids] * 2 + [(i, False) for i in imgs]
    random.shuffle(pool)
    picks = (pool * SEGMENTS)[:SEGMENTS]

    seg_paths = []
    for n, (src, is_video) in enumerate(picks):
        seg = os.path.join(OUTPUT_DIR, f"tg_seg{n}.mp4")
        make_segment(src, is_video, seg)
        seg_paths.append(seg)

    concat_list = os.path.join(OUTPUT_DIR, "tg_concat.txt")
    with open(concat_list, "w") as f:
        f.writelines(f"file '{os.path.abspath(p)}'\n" for p in seg_paths)
    joined = os.path.join(OUTPUT_DIR, "tg_joined.mp4")
    run(["ffmpeg", "-y", "-nostdin", "-f", "concat", "-safe", "0", "-i", concat_list,
         "-c", "copy", joined])

    total = SEG_SECONDS * SEGMENTS
    subs = [{"start": i * SEG_SECONDS, "end": (i + 1) * SEG_SECONDS, "text": b}
            for i, b in enumerate(beats)]
    ass_path = os.path.join(OUTPUT_DIR, "tg.ass")
    # text sits in the upper-middle, clear of TikTok's bottom caption/UI area
    write_ass(ass_path, None, subs, total, sub_y=620)

    date_tag = os.environ.get("RUN_DATE", "today")
    final = os.path.join(OUTPUT_DIR, f"tokyo_girl_{date_tag}.mp4")
    # silent AAC track so TikTok/IG treat it as a normal video; you add the song in-app
    run(["ffmpeg", "-y", "-nostdin", "-i", joined,
         "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
         "-vf", f"ass='{ffmpeg_filter_path(ass_path)}'", "-t", str(total),
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         "-movflags", "+faststart", final])

    caption = strip_emoji(script.get("caption", "")).strip()
    state.setdefault("tokyo_girl_history", []).append(" / ".join(beats))
    save_state(state)

    attach = [final] if os.path.getsize(final) < EMAIL_SAFE_BYTES else []
    body = f"""Today's Tokyo Girl edit ({script.get('theme', theme)})

On-screen text: {' -> '.join(beats)}

TIKTOK CAPTION (copy-paste):
{caption}
{TIKTOK_CREDIT}

INSTAGRAM CAPTION (if you post there too):
{caption}
{IG_CREDIT}

HOW TO POST (about 2 minutes)
1. Save the attached video to your phone and open TikTok -> + -> Upload.
2. Tap "Add sound" and pick the OFFICIAL Tokyo Girl audio:
   https://www.tiktok.com/music/Tokyo-Girl-7705214475481123615
   Keep the song at full volume (the video itself is silent).
3. Paste the caption above (the song credit is required).
4. More options -> Disclose post content -> turn ON "Branded content" (paid-content disclosure).
5. Post, then submit the TikTok link in Content Rewards straight away.
"""
    send_email(f"[Tokyo Girl] Today's TikTok edit - {beats[0]}", body, attach)


if __name__ == "__main__":
    main()
