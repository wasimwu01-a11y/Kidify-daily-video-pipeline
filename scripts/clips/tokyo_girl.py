"""
Placements - "GTA 6 Clipping Campaign - Tokyo Girl" (TikTok / Instagram only).

Makes one ~12 s SILENT vertical GTA 6 edit a day and emails it with a ready
caption. Each of the 3 on-screen text beats gets a matching visual from:

  - your photos in assets/gta6/<folder>/  (folder names = who/where it shows,
    e.g. "Jason and Lucia", "Vice City", "Leonida Keys")
  - Rockstar's official videos, cut straight from rockstargames.com/VI/media:
    the trailers and An Extended Look (streamed, never fully downloaded) and
    the 9 character clips (zip downloaded once, then cached)
  - any .mp4 you add under assets/gta6/ (e.g. your own gameplay after launch)

Silent on purpose: the campaign only pays when the OFFICIAL "Tokyo Girl"
sound is added inside the TikTok/Instagram app, and it bans talking,
voiceovers, game dialogue and trailer music. You add the sound when posting.
"""

import os
import sys
import glob
import json
import random
import zipfile
import subprocess

sys.path.insert(0, os.path.dirname(__file__))
from common import (  # noqa: E402
    OUTPUT_DIR, load_state, save_state, ask_claude_json, strip_emoji,
    write_ass, ffmpeg_filter_path, run, send_email, EMAIL_SAFE_BYTES,
    load_playbook, playbook_prompt, log_posted,
)

ASSET_DIR = os.environ.get("GTA6_ASSET_DIR", "assets/gta6")
ROCKSTAR_CACHE = os.path.expanduser(os.environ.get("ROCKSTAR_CACHE", "~/.cache/rockstar"))
SEGMENTS = 3
SEG_SECONDS = 4.0
TIKTOK_CREDIT = "Song: Tokyo Girl by @Passive"
IG_CREDIT = "Song: Tokyo Girl by @PassiveBand"

RS = "https://media-rockstargames-com.akamaized.net/VI/downloads/videos"
# Official videos from rockstargames.com/VI/media/videos.
# skip = seconds to avoid at the start/end (ratings card, logos, end titles).
ROCKSTAR_VIDEOS = {
    "Trailer 1": (f"{RS}/GTAVI_Trailer_1/GTAVI_Trailer_1.mp4", 10, 15),
    "Trailer 2": (f"{RS}/GTAVI_Trailer_2/GTAVI_Trailer_2.mp4", 10, 15),
    "Launch Trailer": (f"{RS}/GTAVI_Launch_Trailer/GTAVI_Launch_Trailer.mp4", 10, 15),
    "An Extended Look (gameplay)": (f"{RS}/GTAVI_An_Extended_Look/GTAVI_An_Extended_Look.mp4", 30, 30),
}
CLIPS_ZIP = f"{RS}/GTAVI_Videos.zip"   # the 9 character clips + cover art animation

THEMES = [
    "GTA 6 news, trailer details, theories or rumors (on-screen text tells the story)",
    "GTA 6 memes and hype: waiting for the game, launch-day plans, relatable fan jokes",
    "Jason & Lucia relationship memes: couple jokes, partners in crime, annoying your partner",
    "GTA 6 edits and Vice City views: cars, driving, sunsets, beaches, city at night",
]

SYSTEM = """You write on-screen text for silent 12-second GTA 6 TikToks and pick
the visual for each beat.

The video has NO voice - the song "Tokyo Girl" plays over it - so the text
carries the whole joke or story in 3 short beats (one per 4-second shot).

Text rules:
- Each beat max 45 characters, punchy, readable in 2 seconds. English.
- Beat 1 is the hook. Beat 3 is the payoff / punchline.
- No emoji, no hashtags inside the beats, no real brand names besides GTA/Rockstar.
- Never present a rumor as confirmed fact - say "rumor" / "theory".
- Don't repeat recent ideas (given below).

Visual rules:
- For each beat pick ONE source name EXACTLY as written in the list you get.
- Match the beat: a Jason joke shows Jason, a Vice City line shows Vice City.
- Use at least one video source (trailers / clips / gameplay) for motion.

Return ONLY JSON:
{"theme": "...", "beats": ["...", "...", "..."],
 "visuals": ["source name", "source name", "source name"],
 "caption": "short TikTok caption with 3-5 hashtags (no song credit, I add it)"}"""


# ---------------- sources ----------------

def ensure_character_clips() -> dict:
    """Downloads Rockstar's clips zip once (cached between runs by the workflow)."""
    os.makedirs(ROCKSTAR_CACHE, exist_ok=True)
    found = glob.glob(os.path.join(ROCKSTAR_CACHE, "**", "*.mp4"), recursive=True)
    if not found:
        zip_path = os.path.join(ROCKSTAR_CACHE, "clips.zip")
        try:
            print("Downloading Rockstar character clips (first run only)...")
            run(["curl", "-sSfL", "--retry", "3", "-o", zip_path, CLIPS_ZIP])
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(ROCKSTAR_CACHE)
            os.remove(zip_path)
        except Exception as e:
            print(f"Could not get the character clips zip: {e}")
        found = glob.glob(os.path.join(ROCKSTAR_CACHE, "**", "*.mp4"), recursive=True)
    clips = {}
    for path in found:
        name = os.path.splitext(os.path.basename(path))[0]
        name = name.replace("GTAVI_", "").replace("_", " ").strip()
        clips[f"Clip: {name}"] = path
    return clips


def catalogue() -> tuple[dict, dict]:
    """photos: {folder name: [files]}, videos: {name: (path_or_url, skip_start, skip_end)}"""
    photos = {}
    for ext in ("jpg", "jpeg", "png", "webp"):
        for path in glob.glob(os.path.join(ASSET_DIR, "**", f"*.{ext}"), recursive=True):
            rel = os.path.relpath(path, ASSET_DIR)
            folder = rel.split(os.sep)[0] if os.sep in rel else "Misc screenshots"
            photos.setdefault(f"Photos: {folder}", []).append(path)

    videos = {name: v for name, v in ROCKSTAR_VIDEOS.items()}
    for name, path in ensure_character_clips().items():
        videos[name] = (path, 0, 0)
    for path in glob.glob(os.path.join(ASSET_DIR, "**", "*.mp4"), recursive=True):
        videos[f"My clip: {os.path.splitext(os.path.basename(path))[0]}"] = (path, 0, 0)
    return photos, videos


# ---------------- rendering ----------------

def media_duration(src: str) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", src]).stdout.strip()
    return float(out or 0)


def frame_brightness(path: str) -> float:
    """Mean brightness (0-255) of the segment's middle frame - rejects black/title cards."""
    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", str(SEG_SECONDS / 2), "-i", path,
         "-frames:v", "1", "-vf", "scale=32:32,format=gray", "-f", "rawvideo", "-"],
        capture_output=True).stdout
    return sum(out) / len(out) if out else 0


FIT = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
       "setsar=1,fps=30,format=yuv420p")


def video_segment(src: str, skip_start: float, skip_end: float, out: str) -> bool:
    try:
        dur = media_duration(src)
    except Exception as e:
        print(f"Can't read {src}: {e}")
        return False
    lo, hi = skip_start, max(skip_start, dur - skip_end - SEG_SECONDS)
    for _ in range(4):  # retry if we land on a black frame / title card
        start = random.uniform(lo, hi) if hi > lo else 0
        try:
            run(["ffmpeg", "-y", "-nostdin", "-ss", f"{start:.2f}", "-i", src,
                 "-t", str(SEG_SECONDS), "-an", "-vf", FIT,
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out])
        except Exception as e:
            print(f"Segment failed from {src}: {e}")
            return False
        if frame_brightness(out) > 28:
            return True
        print("Dark frame, trying another moment...")
    return True


def photo_segment(src: str, out: str):
    frames = int(SEG_SECONDS * 30)
    zx = random.choice(["iw/2-(iw/zoom/2)", "0", "iw-iw/zoom"])  # vary the pan
    zoom = (f"scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,"
            f"zoompan=z='min(zoom+0.0012,1.2)':x='{zx}':y='ih/2-(ih/zoom/2)'"
            f":d={frames}:s=1080x1920:fps=30,setsar=1,format=yuv420p")
    run(["ffmpeg", "-y", "-nostdin", "-loop", "1", "-i", src,
         "-t", str(SEG_SECONDS), "-vf", zoom,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out])


def make_segment(choice: str, photos: dict, videos: dict, used: set, out: str):
    if choice in videos:
        src, s0, s1 = videos[choice]
        if video_segment(src, s0, s1, out):
            return
        choice = random.choice(list(photos)) if photos else None
    if choice in photos:
        options = [p for p in photos[choice] if p not in used] or photos[choice]
        pick = random.choice(options)
        used.add(pick)
        photo_segment(pick, out)
        return
    raise RuntimeError("No usable visual source")


# ---------------- main ----------------

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    photos, videos = catalogue()
    if not photos and not videos:
        send_email("[Tokyo Girl] No GTA 6 footage available",
                   f"Add screenshots to {ASSET_DIR}/ in the repo.")
        return
    print(f"Sources: {len(photos)} photo folders, {len(videos)} videos")

    state = load_state()
    history = state.get("tokyo_girl_history", [])[-20:]
    theme = THEMES[len(state.get("tokyo_girl_history", [])) % len(THEMES)]
    source_list = ([f"{n}  ({len(v)} photos)" for n, v in photos.items()]
                   + [f"{n}  (video)" for n in videos])
    pb = load_playbook("tokyo_girl")
    style = pb.get("style", {})
    if pb:
        print(f"Using playbook from {pb.get('updated')}: {pb.get('summary', '')[:200]}")
    script = ask_claude_json(
        SYSTEM + playbook_prompt(pb),
        f"Theme for today: {theme}\nRecent ideas to avoid: {json.dumps(history)}\n\n"
        "Available visual sources (use the name before the brackets):\n- "
        + "\n- ".join(source_list),
        max_tokens=900,
    )
    beats = [strip_emoji(b)[:50] for b in script["beats"][:SEGMENTS]]
    if style.get("subtitle_case") == "upper" or style.get("hook_text") == "upper":
        beats = [b.upper() for b in beats]
    all_names = list(photos) + list(videos)
    visuals = [v.split("  (")[0].strip() for v in script.get("visuals", [])][:SEGMENTS]
    visuals = [v if v in all_names else random.choice(all_names) for v in visuals]
    while len(visuals) < SEGMENTS:
        visuals.append(random.choice(all_names))
    print("Beats:", beats, "\nVisuals:", visuals)

    used, seg_paths = set(), []
    for n, choice in enumerate(visuals):
        seg = os.path.join(OUTPUT_DIR, f"tg_seg{n}.mp4")
        make_segment(choice, photos, videos, used, seg)
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
    write_ass(ass_path, None, subs, total, sub_y=620,  # clear of TikTok's bottom UI
              sub_size=84 if style.get("subtitle_size") == "large" else 68)

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
    extra = [h for h in pb.get("hashtags", []) if h.lower() not in caption.lower()][:3]
    if extra:
        caption = f"{caption} {' '.join(extra)}"
    state.setdefault("tokyo_girl_history", []).append(" / ".join(beats))
    log_posted(state, {"campaign": "tokyo_girl", "date": date_tag, "hook": beats[0],
                       "title": caption[:120], "style": style, "visuals": visuals})
    save_state(state)

    attach = [final] if os.path.getsize(final) < EMAIL_SAFE_BYTES else []
    shots = "\n".join(f"  {i + 1}. {b}  [{v}]" for i, (b, v) in enumerate(zip(beats, visuals)))
    body = f"""Today's Tokyo Girl edit ({script.get('theme', theme)})

Shots:
{shots}

TIKTOK CAPTION (copy-paste):
{caption}
{TIKTOK_CREDIT}

INSTAGRAM CAPTION (if you post there too):
{caption}
{IG_CREDIT}

HOW TO POST (about 2 minutes)
1. Save the attached video to your phone.
2. Open the official sound: https://www.tiktok.com/music/Tokyo-Girl-7705214475481123615
   -> "Use sound" -> Upload -> pick the video. (Or: Add sound -> Favorites -> Tokyo Girl.)
3. Paste the caption above (the song credit is required).
4. More options -> Disclose post content -> turn ON "Branded content".
5. Post, then submit the TikTok link in Content Rewards straight away.
"""
    send_email(f"[Tokyo Girl] Today's TikTok edit - {beats[0]}", body, attach)


if __name__ == "__main__":
    main()
