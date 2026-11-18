"""
Trend research: learns what's getting views and writes a "playbook" that the
editors (kick_clipper.py, tokyo_girl.py) follow.

Signals, per campaign:
  1. Content Rewards campaign page -> its top 20 clips (caption, views,
     platform and the actual video file). For the top few we pull frames
     (Claude looks at them: hook text, caption style, framing) and transcribe
     the first seconds (the spoken hook).
  2. YouTube trending Shorts for the topic (needs the optional
     YOUTUBE_API_KEY secret): titles, descriptions, tags, length, views and
     thumbnails.
  3. Our own posted clips and how many views they got (also via
     YOUTUBE_API_KEY), so the agent keeps what works for this channel.

Claude turns all of that into state/playbook_<campaign>.json:
moments to pick, hook/title/caption formulas, hashtags, target length,
visual style (caption size/case, words per caption, framing), things to
avoid, and one small experiment per cycle so it keeps learning.

Runs every RESEARCH_EVERY_DAYS days (default 3) or when FORCE_RESEARCH=true.
Usage: python research.py            (all campaigns)
       python research.py tjr        (just one)
"""

import os
import sys
import json
import base64
import tempfile
import subprocess
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from common import (  # noqa: E402
    load_state, ask_claude_json_blocks, load_playbook, playbook_path, run,
)
from campaigns import all_campaigns, research_targets  # noqa: E402

EVERY_DAYS = float(os.environ.get("RESEARCH_EVERY_DAYS", "3"))
FORCE = os.environ.get("FORCE_RESEARCH", "").lower() in ("1", "true", "yes")
YT_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
TOP_CLIPS_TO_WATCH = 6
FRAMES_PER_CLIP = 4
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


# ---------------- Content Rewards ----------------

def parse_top_clips(html: str) -> list[dict]:
    """The campaign page embeds its data as an escaped JSON string; pull out "topClips"."""
    for marker, escaped in (('topClips\\":', True), ('"topClips":', False)):
        i = html.find(marker)
        if i == -1:
            continue
        chunk = html[i + len(marker): i + len(marker) + 300_000]
        if escaped:  # undo the JS-string escaping: \\ -> \ and \" -> "
            chunk = chunk.replace("\\\\", "\x00").replace('\\"', '"').replace("\x00", "\\")
        try:
            clips, _ = json.JSONDecoder().raw_decode(chunk.lstrip())
            return [c for c in clips if isinstance(c, dict)]
        except json.JSONDecodeError as e:
            print(f"Could not decode topClips ({e})")
    return []


def fetch_campaign_top_clips(campaign_id: str) -> list[dict]:
    from curl_cffi import requests as creq
    url = f"https://contentrewards.com/c/campaigns/{campaign_id}"
    r = creq.get(url, impersonate="chrome", timeout=40)
    r.raise_for_status()
    clips = parse_top_clips(r.text)
    print(f"Content Rewards: {len(clips)} top clips")
    return sorted(clips, key=lambda c: -(c.get("totalViews") or 0))


def probe(path: str) -> dict:
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height:format=duration",
               "-of", "json", path]).stdout
    d = json.loads(out)
    st = (d.get("streams") or [{}])[0]
    return {"duration": round(float(d.get("format", {}).get("duration", 0)), 1),
            "width": st.get("width"), "height": st.get("height")}


def grab_frames(path: str, duration: float, n: int) -> list[str]:
    """Small JPEG frames at the hook (0.5s, 2s) and later in the clip, base64."""
    times = [0.5, 2.0] + [duration * f for f in (0.45, 0.8)]
    frames = []
    for t in times[:n]:
        if t >= duration:
            continue
        out = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", path,
             "-frames:v", "1", "-vf", "scale=-2:640", "-q:v", "5", "-f", "image2", "-c:v", "mjpeg", "-"],
            capture_output=True).stdout
        if out:
            frames.append(base64.b64encode(out).decode())
    return frames


_whisper = None


def hook_transcript(path: str, language: str) -> str:
    global _whisper
    try:
        if _whisper is None:
            from faster_whisper import WhisperModel
            _whisper = WhisperModel(os.environ.get("WHISPER_MODEL", "small"),
                                    device="cpu", compute_type="int8")
        wav = path + ".wav"
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", path, "-t", "10",
                        "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
        segs, _ = _whisper.transcribe(wav, language=language, vad_filter=True)
        return " ".join(s.text.strip() for s in segs)[:300]
    except Exception as e:
        print(f"Hook transcription skipped: {e}")
        return ""


def study_clip(clip: dict, workdir: str, language: str | None) -> dict:
    import requests
    info = {"rank": clip.get("rank"), "views": clip.get("totalViews"),
            "platform": clip.get("platform"), "caption": (clip.get("title") or "")[:300]}
    url = clip.get("videoUrl")
    if not url:
        return info
    path = os.path.join(workdir, f"top_{clip.get('rank')}.mp4")
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=90)
        r.raise_for_status()
        if len(r.content) > 80 * 1024 * 1024:
            return info
        with open(path, "wb") as f:
            f.write(r.content)
        info.update(probe(path))
        info["frames"] = grab_frames(path, info["duration"], FRAMES_PER_CLIP)
        if language:
            info["spoken_hook"] = hook_transcript(path, language)
    except Exception as e:
        print(f"Couldn't study clip #{clip.get('rank')}: {e}")
    return info


# ---------------- YouTube ----------------

def yt_get(endpoint: str, **params) -> dict:
    import requests
    params["key"] = YT_KEY
    r = requests.get(f"https://www.googleapis.com/youtube/v3/{endpoint}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def iso_duration_s(d: str) -> int:
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def youtube_trending(query: str, language: str) -> list[dict]:
    if not YT_KEY or not query:
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    found = yt_get("search", part="id", q=query, type="video", videoDuration="short",
                   order="viewCount", publishedAfter=since, maxResults=15,
                   relevanceLanguage=language)
    ids = [it["id"]["videoId"] for it in found.get("items", [])]
    if not ids:
        return []
    vids = yt_get("videos", part="snippet,statistics,contentDetails", id=",".join(ids))
    out = []
    for v in vids.get("items", []):
        sn, st = v["snippet"], v.get("statistics", {})
        out.append({"title": sn.get("title"), "description": (sn.get("description") or "")[:300],
                    "tags": (sn.get("tags") or [])[:10], "views": int(st.get("viewCount", 0)),
                    "likes": int(st.get("likeCount", 0)), "comments": int(st.get("commentCount", 0)),
                    "duration_s": iso_duration_s(v["contentDetails"].get("duration")),
                    "thumb": sn.get("thumbnails", {}).get("high", {}).get("url")})
    out.sort(key=lambda x: -x["views"])
    print(f"YouTube: {len(out)} trending Shorts for '{query}'")
    return out[:10]


def our_results(state: dict, campaign: str) -> list[dict]:
    posted = [p for p in state.get("posted", []) if p.get("campaign") == campaign and p.get("video_id")]
    if not posted:
        return []
    if not YT_KEY:
        return [{k: p.get(k) for k in ("date", "hook", "title", "style")} for p in posted[-10:]]
    stats = {}
    ids = [p["video_id"] for p in posted[-40:]]
    for i in range(0, len(ids), 50):
        for v in yt_get("videos", part="statistics", id=",".join(ids[i:i + 50])).get("items", []):
            stats[v["id"]] = v.get("statistics", {})
    rows = []
    for p in posted[-40:]:
        st = stats.get(p["video_id"])
        if st is None:
            continue  # not public yet or deleted
        rows.append({"date": p.get("date"), "hook": p.get("hook"), "title": p.get("title"),
                     "style": p.get("style"), "views": int(st.get("viewCount", 0)),
                     "likes": int(st.get("likeCount", 0)), "comments": int(st.get("commentCount", 0))})
    return rows


def b64_url_image(url: str) -> str | None:
    import requests
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
        r.raise_for_status()
        return base64.b64encode(r.content).decode()
    except Exception:
        return None


# ---------------- Claude ----------------

SYSTEM = """You are a short-form video strategist for an automated clipping channel.
You study what is getting views RIGHT NOW (a campaign's top clips, trending
Shorts on the topic, and our own past results) and write a playbook that our
automated editor follows for the next few days.

Learn PATTERNS: which moments get picked, how the first 2 seconds hook,
on-screen text style, caption size/case and how many words appear at once,
framing, length, title/caption wording and hashtags. Weigh by views, and say
what separates the top clips from the rest.

Hard limits:
- Never copy another creator's caption, title or on-screen text word for word,
  and never suggest reusing their footage. Write ORIGINAL examples in the style.
- The campaign's own rules always win over trends (they are given below).
- Our editor can only control the options listed in "style"; describe other
  observations in the text fields.
- Be concrete. "Use engaging hooks" is useless; "open on the punchline as a
  question in 4-6 words, e.g. ..." is useful.

Return ONLY JSON:
{
 "summary": "3-5 sentences: what the top performers have in common",
 "moments_to_pick": ["kind of moment that performs", "..."],
 "hook_examples": ["original example hook in the winning style", "..."],
 "title_formula": "how to write the YouTube title",
 "caption_formula": "how to write the post caption/description",
 "hashtags": ["#tag", "..."],
 "target_length": [min_seconds, max_seconds],
 "style": {
   "hook_text": "upper" | "sentence" | "none",
   "subtitle_case": "upper" | "sentence",
   "subtitle_size": "normal" | "large",
   "words_per_caption": 1-8,
   "framing": "blur_fill" | "big_center"
 },
 "avoid": ["...", "..."],
 "experiment": "one small, specific thing to try differently this cycle",
 "our_results_note": "what our own numbers say (or 'not enough data yet')"
}

Style options: blur_fill = whole 16:9 stream frame in the middle with a
blurred copy filling the background; big_center = stream frame enlarged
(sides cropped) so faces are bigger. words_per_caption = how many words of
subtitle show at once (2-3 = fast punchy captions, 6-8 = full sentences)."""


def research(name: str, state: dict) -> dict | None:
    cfg = research_targets(state)[name]
    rules = all_campaigns(state).get(name, {}).get("rules") or cfg.get("rules", "")
    language = cfg.get("language")
    content: list[dict] = []
    summary_rows = []

    with tempfile.TemporaryDirectory() as tmp:
        top = []
        try:
            top = fetch_campaign_top_clips(cfg["content_rewards_id"])
        except Exception as e:
            print(f"Content Rewards fetch failed: {e}")
        for clip in top[TOP_CLIPS_TO_WATCH:20]:
            summary_rows.append({"rank": clip.get("rank"), "views": clip.get("totalViews"),
                                 "platform": clip.get("platform"),
                                 "caption": (clip.get("title") or "")[:200]})
        studied = [study_clip(c, tmp, language if cfg.get("transcribe", True) else None)
                   for c in top[:TOP_CLIPS_TO_WATCH]]

    content.append({"type": "text", "text":
                    f"CAMPAIGN: {name}\nCAMPAIGN RULES:\n{rules}\n\n"
                    f"Topic notes: {cfg.get('notes', '')}\n\n"
                    "=== TOP CLIPS IN THIS CAMPAIGN (studied in detail) ==="})
    for c in studied:
        frames = c.pop("frames", [])
        content.append({"type": "text", "text": json.dumps(c, ensure_ascii=False)
                        + f"\nFrames (0.5s, 2s, 45%, 80%) of clip rank {c.get('rank')}:"})
        for fr in frames:
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": fr}})
    if summary_rows:
        content.append({"type": "text", "text": "=== MORE TOP CLIPS (captions + views) ===\n"
                        + json.dumps(summary_rows, ensure_ascii=False)})

    try:
        trending = youtube_trending(cfg.get("youtube_query", ""), language or "en")
    except Exception as e:
        print(f"YouTube trending failed: {e}")
        trending = []
    if trending:
        content.append({"type": "text", "text": "=== TRENDING YOUTUBE SHORTS ON THIS TOPIC (last 14 days) ===\n"
                        + json.dumps([{k: v for k, v in t.items() if k != "thumb"} for t in trending],
                                     ensure_ascii=False)})
        for t in trending[:3]:
            img = b64_url_image(t["thumb"]) if t.get("thumb") else None
            if img:
                content.append({"type": "text", "text": f"Thumbnail of: {t['title']} ({t['views']} views)"})
                content.append({"type": "image",
                                "source": {"type": "base64", "media_type": "image/jpeg", "data": img}})

    try:
        ours = our_results(state, name)
    except Exception as e:
        print(f"Own results failed: {e}")
        ours = []
    content.append({"type": "text", "text": "=== OUR OWN RECENT POSTS ===\n"
                    + (json.dumps(ours, ensure_ascii=False) if ours else "none yet")})
    previous = load_playbook(name)
    if previous:
        content.append({"type": "text", "text": "=== OUR PREVIOUS PLAYBOOK (update it; keep what our numbers support) ===\n"
                        + json.dumps(previous, ensure_ascii=False)})

    if not studied and not summary_rows and not trending:
        print("No research data collected - keeping the old playbook.")
        return None

    pb = ask_claude_json_blocks(SYSTEM, content, max_tokens=3000)
    return sanitise(pb, name, state)


def sanitise(pb: dict, name: str, state: dict | None = None) -> dict:
    """Clamp everything to values the editors understand."""
    style = pb.get("style") or {}
    camp = all_campaigns(state or {}).get(name, {})
    lo = camp.get("min_clip", 8)
    hi = camp.get("max_clip", 60)
    tl = pb.get("target_length") or [lo, hi]
    try:
        tmin = max(lo, min(float(tl[0]), hi))
        tmax = max(tmin, min(float(tl[1]), hi))
    except (TypeError, ValueError, IndexError):
        tmin, tmax = lo, hi

    def pick(val, options, default):
        return val if val in options else default

    tags = [t if t.startswith("#") else f"#{t}" for t in (pb.get("hashtags") or []) if isinstance(t, str)]
    return {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "summary": str(pb.get("summary", ""))[:800],
        "moments_to_pick": [str(x)[:200] for x in (pb.get("moments_to_pick") or [])][:6],
        "hook_examples": [str(x)[:80] for x in (pb.get("hook_examples") or [])][:6],
        "title_formula": str(pb.get("title_formula", ""))[:300],
        "caption_formula": str(pb.get("caption_formula", ""))[:300],
        "hashtags": [t.replace(" ", "")[:30] for t in tags][:6],
        "target_length": [round(tmin), round(tmax)],
        "style": {
            "hook_text": pick(style.get("hook_text"), ("upper", "sentence", "none"), "sentence"),
            "subtitle_case": pick(style.get("subtitle_case"), ("upper", "sentence"), "sentence"),
            "subtitle_size": pick(style.get("subtitle_size"), ("normal", "large"), "normal"),
            "words_per_caption": max(1, min(int(style.get("words_per_caption") or 6), 8)),
            "framing": pick(style.get("framing"), ("blur_fill", "big_center"), "blur_fill"),
        },
        "avoid": [str(x)[:200] for x in (pb.get("avoid") or [])][:6],
        "experiment": str(pb.get("experiment", ""))[:300],
        "our_results_note": str(pb.get("our_results_note", ""))[:300],
    }


def is_stale(name: str) -> bool:
    pb = load_playbook(name)
    if FORCE or not pb.get("updated"):
        return True
    age = datetime.now(timezone.utc) - datetime.strptime(pb["updated"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return age >= timedelta(days=EVERY_DAYS)


def main(names: list[str] | None = None):
    state = load_state()
    targets, camps = research_targets(state), all_campaigns(state)
    for name in names or list(targets):
        if name not in targets:
            print(f"Unknown research target: {name}")
            continue
        if name in state.get("retired", []) or (name in camps and not camps[name].get("enabled", True)):
            print(f"[{name}] paused - skipping research")
            continue
        if not is_stale(name):
            print(f"[{name}] playbook is fresh - skipping (set FORCE_RESEARCH=true to redo)")
            continue
        print(f"[{name}] researching what's getting views...")
        try:
            pb = research(name, state)
        except Exception as e:
            print(f"[{name}] research failed: {e}")
            continue
        if pb:
            os.makedirs(os.path.dirname(playbook_path(name)) or ".", exist_ok=True)
            with open(playbook_path(name), "w") as f:
                json.dump(pb, f, indent=2, ensure_ascii=False)
            print(f"[{name}] new playbook:\n{json.dumps(pb, indent=2, ensure_ascii=False)}")


if __name__ == "__main__":
    main(sys.argv[1:] or None)
