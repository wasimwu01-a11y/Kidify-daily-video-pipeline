"""
Kick stream clipper for Content Rewards campaigns (Bichou, TJR, ...).
Campaign settings live in campaigns.py. Run:  python kick_clipper.py <campaign>

Daily flow per campaign:
  1. Pick the streamer's newest Kick VOD not clipped yet (prefers titles that
     match the campaign's themes, skips casino-looking titles).
  2. Decode its audio from the lowest-quality stream, score each second by
     loudness spikes vs. the surrounding 5 minutes, keep the best ~12 moments.
  3. Transcribe those moments with faster-whisper (free, CPU).
  4. Claude picks the best clips under the campaign rules and returns
     corrected, timed subtitles.
  5. FFmpeg renders 1080x1920: blurred background + full stream frame in the
     middle, hook title on top, subtitles below.
  6. Uploads each clip to YouTube as PRIVATE and emails it with next steps
     (you make it public when you're ready to submit within 30 minutes).
"""

import os
import re
import sys
import json
import subprocess
from datetime import datetime, timezone
from urllib.parse import urljoin

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from common import (  # noqa: E402
    OUTPUT_DIR, load_state, save_state, ask_claude_json, remove_currency_symbols,
    strip_emoji, write_ass, ffmpeg_filter_path, run, youtube_upload_private,
    send_email, EMAIL_SAFE_BYTES, load_playbook, playbook_prompt, log_posted,
    approve_block, new_token, short_id,
)
from campaigns import all_campaigns  # noqa: E402

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
MAX_ANALYSE_SECONDS = int(os.environ.get("MAX_ANALYSE_SECONDS", str(4 * 3600)))
N_CANDIDATES = 12
WINDOW_BEFORE, WINDOW_AFTER = 50, 30
SR = 16000
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


# ---------------- Kick ----------------

def kick_get(url: str):
    """Kick's API sits behind Cloudflare; curl_cffi impersonates a real browser."""
    from curl_cffi import requests as creq
    r = creq.get(url, impersonate="chrome", timeout=30)
    r.raise_for_status()
    return r.json()


def list_vods(channel: str) -> list[dict]:
    data = kick_get(f"https://kick.com/api/v2/channels/{channel}/videos")
    if isinstance(data, dict):
        data = data.get("data") or data.get("videos") or []
    vods = []
    for item in data:
        video = item.get("video") or {}
        uuid = video.get("uuid") or item.get("uuid") or str(item.get("id"))
        cats = item.get("categories") or []
        vods.append({
            "uuid": uuid,
            "title": item.get("session_title") or video.get("title") or "",
            "categories": " ".join(str(c.get("name", "")) for c in cats if isinstance(c, dict)),
            "created_at": item.get("created_at") or "",
            "duration_s": (item.get("duration") or 0) / 1000,
            "source": item.get("source") or video.get("source"),
            "url": f"https://kick.com/{channel}/videos/{uuid}",
            "channel": channel,
        })
    return vods


def category_channels(cfg: dict, limit: int = 10) -> list[str]:
    """Streamers currently live in a Kick category, filtered by language, biggest first."""
    if cfg.get("kick_channels"):
        return list(cfg["kick_channels"])
    found = []
    for page in (1, 2, 3):
        try:
            data = kick_get(f"https://kick.com/stream/livestreams/en?limit=24&page={page}"
                            f"&sort=desc&subcategory={cfg['kick_category']}")
        except Exception as e:
            print(f"Category lookup failed: {e}")
            break
        for x in data.get("data", []):
            ch = (x.get("channel") or {}).get("slug") or x.get("slug")
            lang = str(x.get("language", ""))
            if ch and lang.lower() in (cfg.get("kick_language", "English").lower(), "en") and ch not in found:
                found.append(ch)
        if not data.get("next_page_url"):
            break
    print(f"Live {cfg['kick_category']} streamers ({cfg.get('kick_language')}): {found[:limit]}")
    return found[:limit]


def vod_from_url(url: str) -> dict:
    """Manual override: a kick.com/<channel>/videos/<uuid> link."""
    uuid = url.rstrip("/").split("/")[-1]
    data = kick_get(f"https://kick.com/api/v1/video/{uuid}")
    return {"uuid": uuid, "title": (data.get("livestream") or {}).get("session_title", ""),
            "duration_s": 0, "source": data["source"], "url": url}


def pick_vod(cfg: dict, state: dict) -> dict | None:
    manual = os.environ.get("VOD_URL", "").strip()
    if manual and cfg.get("kick_channel") and f"kick.com/{cfg['kick_channel']}/" in manual:
        return vod_from_url(manual)
    done = set(state.get("processed_vods", []))
    skip = re.compile(cfg["skip_title"], re.I) if cfg["skip_title"] else None
    prefer = re.compile(cfg["prefer_title"], re.I) if cfg["prefer_title"] else None
    need = re.compile(cfg["require_title"], re.I) if cfg.get("require_title") else None
    channels = [cfg["kick_channel"]] if cfg.get("kick_channel") else category_channels(cfg)
    vods = []
    for ch in channels:
        try:
            vods += list_vods(ch)[:6 if len(channels) > 1 else 15]
        except Exception as e:
            print(f"Can't list {ch}'s VODs: {e}")
    fresh = []
    for vod in vods:  # each channel newest first; channels biggest first
        if vod["uuid"] in done or not vod["source"]:
            continue
        if need and not need.search(f"{vod['title']} {vod.get('categories', '')}"):
            continue
        if skip and skip.search(vod["title"]):
            print(f"Skipping VOD (title filter): {vod['title']}")
            continue
        if vod["duration_s"] and vod["duration_s"] < 15 * 60:
            continue
        fresh.append(vod)
    if prefer:
        for vod in fresh:
            if prefer.search(vod["title"]):
                return vod
    return fresh[0] if fresh else None


def variant_urls(master_url: str) -> tuple[str, str]:
    """(lowest-quality URL for audio analysis, best <=1080p URL for clips)."""
    import requests
    text = requests.get(master_url, headers={"User-Agent": UA}, timeout=30).text
    if "#EXT-X-STREAM-INF" not in text:
        return master_url, master_url
    variants = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            m = re.search(r"RESOLUTION=(\d+)x(\d+)", line)
            variants.append((int(m.group(2)) if m else 0, urljoin(master_url, lines[i + 1].strip())))
    variants.sort()
    best = [v for v in variants if v[0] <= 1080] or variants
    return variants[0][1], best[-1][1]


# ---------------- moment finding ----------------

def http_opts(url: str) -> list[str]:
    return ["-user_agent", UA] if url.startswith("http") else []


def load_audio(url: str) -> np.ndarray:
    print("Decoding VOD audio for analysis (this is the slow part)...")
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", *http_opts(url),
         "-t", str(MAX_ANALYSE_SECONDS), "-i", url,
         "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
        capture_output=True, check=True,
    )
    audio = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    print(f"Audio decoded: {len(audio) / SR / 60:.1f} minutes")
    return audio


def find_peaks(audio: np.ndarray) -> list[int]:
    secs = len(audio) // SR
    frames = audio[: secs * SR].reshape(secs, SR)
    rms_db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    smooth = np.convolve(rms_db, np.ones(3) / 3, mode="same")
    half = 150
    baseline = np.array([np.median(smooth[max(0, i - half): i + half]) for i in range(0, secs, 10)])
    baseline = np.repeat(baseline, 10)[:secs]
    score = smooth - baseline
    score[:120] = -99
    score[-60:] = -99
    peaks = []
    for idx in np.argsort(score)[::-1]:
        if len(peaks) >= N_CANDIDATES or score[idx] < -50:
            break
        if all(abs(int(idx) - p) > 120 for p in peaks):
            peaks.append(int(idx))
    return sorted(peaks)


def transcribe_windows(audio: np.ndarray, peaks: list[int], language: str) -> list[dict]:
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    total = len(audio) / SR
    candidates = []
    for n, p in enumerate(peaks):
        start = max(0, p - WINDOW_BEFORE)
        end = min(total, p + WINDOW_AFTER)
        chunk = audio[int(start * SR): int(end * SR)]
        segments, _ = model.transcribe(chunk, language=language, vad_filter=True, beam_size=5)
        segs = [{"start": round(start + s.start, 2), "end": round(start + s.end, 2),
                 "text": s.text.strip()} for s in segments if s.text.strip()]
        print(f"Candidate {n}: {start:.0f}-{end:.0f}s, {len(segs)} segments")
        candidates.append({"candidate": n, "window_start": round(start, 2),
                           "window_end": round(end, 2), "segments": segs})
    return candidates


# ---------------- Claude selection ----------------

def target_length(cfg: dict, pb: dict) -> tuple[float, float]:
    """Playbook's preferred length, clamped to the campaign's hard limits."""
    lo, hi = cfg["min_clip"], cfg["max_clip"]
    t = pb.get("target_length") or [lo, hi]
    tmin = max(lo, min(float(t[0]), hi))
    return tmin, max(tmin, min(float(t[1]), hi))


def build_system(cfg: dict, pb: dict | None = None) -> str:
    pb = pb or {}
    tmin, tmax = target_length(cfg, pb)
    return f"""{cfg['rules']}
{playbook_prompt(pb)}

You receive candidate moments from a Kick stream with automatic Whisper
transcripts (timestamps in absolute seconds). Choose up to {cfg['clips_per_day']}
clips that will get the most views as short-form videos.

Technical rules:
- Each clip is {tmin:.0f}-{tmax:.0f} seconds long and stays inside its
  candidate's window. Start just before the action, end on the payoff/reaction.
- Subtitles: keep Whisper's timestamps but split into short lines
  (max 2 lines, ~38 characters per line). Same language as the stream.
- No emoji anywhere.
- If no moment is good enough or within the rules, return an empty list.

Answer ONLY with JSON:
{{"clips": [{{
  "candidate": 0,
  "start": 1234.5,
  "end": 1275.0,
  "hook": "on-screen title, max 40 characters",
  "youtube_title": "YouTube title, max 80 characters",
  "reason": "why this moment will work",
  "subtitles": [{{"start": 1234.6, "end": 1237.1, "text": "..."}}]
}}]}}"""


def choose_clips(cfg: dict, candidates: list[dict], vod_title: str, pb: dict | None = None) -> list[dict]:
    usable = [c for c in candidates if len(c["segments"]) >= 3]
    if not usable:
        return []
    clean = (lambda t: strip_emoji(remove_currency_symbols(t))) if cfg["no_currency_symbols"] \
        else (lambda t: strip_emoji(t))
    result = ask_claude_json(build_system(cfg, pb),
                             f"Stream title: {vod_title}\n\nCandidates:\n"
                             + json.dumps(usable, ensure_ascii=False), max_tokens=8000)
    clips = result.get("clips", []) if isinstance(result, dict) else result
    by_id = {c["candidate"]: c for c in candidates}
    valid = []
    for clip in clips[:cfg["clips_per_day"]]:
        cand = by_id.get(clip.get("candidate"))
        if cand is None:
            continue
        start = max(float(clip["start"]), cand["window_start"])
        end = min(float(clip["end"]), cand["window_end"])
        if end - start < cfg["min_clip"]:
            end = min(cand["window_end"], start + cfg["min_clip"])
            start = max(cand["window_start"], end - cfg["min_clip"])
        if end - start < cfg["min_clip"] - 1.5:
            print(f"Dropping candidate {cand['candidate']}: too short ({end - start:.1f}s)")
            continue
        end = min(end, start + cfg["max_clip"])
        subs = []
        for s in clip.get("subtitles", []):
            text = clean(str(s.get("text", "")))
            rs, re_ = float(s["start"]) - start, float(s["end"]) - start
            if text and re_ > 0 and rs < end - start:
                subs.append({"start": max(rs, 0), "end": min(re_, end - start), "text": text})
        if not subs:
            print(f"Dropping candidate {cand['candidate']}: no subtitles")
            continue
        valid.append({"start": start, "end": end, "subs": subs,
                      "hook": clean(clip.get("hook", ""))[:45],
                      "youtube_title": clean(clip.get("youtube_title", ""))[:80],
                      "reason": clip.get("reason", "")})
    return valid


# ---------------- render ----------------

DEFAULT_STYLE = {"hook_text": "sentence", "subtitle_case": "sentence", "subtitle_size": "normal",
                 "words_per_caption": 8, "framing": "blur_fill"}


def chunk_subs(subs: list[dict], words_per_caption: int) -> list[dict]:
    """Splits subtitle lines into chunks of N words, timing split by word count."""
    out = []
    for s in subs:
        words = s["text"].split()
        if len(words) <= words_per_caption:
            out.append(s)
            continue
        groups = [words[i:i + words_per_caption] for i in range(0, len(words), words_per_caption)]
        span, t = s["end"] - s["start"], s["start"]
        for g in groups:
            d = span * len(g) / len(words)
            out.append({"start": t, "end": t + d, "text": " ".join(g)})
            t += d
    return out


def render_clip(src_url: str, clip: dict, out_path: str, style: dict | None = None,
                logo: dict | None = None):
    st = {**DEFAULT_STYLE, **(style or {})}
    if logo:
        st["framing"] = "blur_fill"   # keeps room under the gameplay for the logo
    duration = clip["end"] - clip["start"]
    ass_path = out_path.replace(".mp4", ".ass")
    subs = chunk_subs(clip["subs"], st["words_per_caption"])
    if st["subtitle_case"] == "upper":
        subs = [{**s, "text": s["text"].upper()} for s in subs]
    hook = None if st["hook_text"] == "none" else clip["hook"]
    if hook and st["hook_text"] == "upper":
        hook = hook.upper()
    big = st["framing"] == "big_center"
    # blur_fill: 1080x608 frame centred (y 656-1264); big_center: 1512x851 cropped to 1080 wide
    fg_h = 851 if big else 608
    top_of_video = (1920 - fg_h) // 2
    if logo:
        # hook at the top, subtitles just ABOVE the gameplay, logo BELOW it: nothing covers the logo
        sub_y, title_y = top_of_video - 200, 190
    else:
        sub_y, title_y = top_of_video + fg_h + 40, max(top_of_video - 230, 180)
    write_ass(ass_path, hook, subs, duration, sub_y=sub_y, title_y=title_y,
              sub_size=84 if st["subtitle_size"] == "large" else 68)
    fg = "[b]scale=1512:-2,crop=1080:ih[fg];" if big else "[b]scale=1080:-2[fg];"
    vf = (
        "[0:v]split[a][b];"
        "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "boxblur=20:2,eq=brightness=-0.12[bg];"
        + fg +
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,ass='{ffmpeg_filter_path(ass_path)}',fps=30"
    )
    logo_inputs = []
    if logo:
        # same proportions as the file (no stretch/crop/recolour), large and fully on screen
        vf += f"[base];[1:v]scale={int(logo['width'])}:-1[lg];[base][lg]overlay=(W-w)/2:{top_of_video + fg_h + 45}[v]"
        logo_inputs = ["-loop", "1", "-i", logo["file"]]
    else:
        vf += "[v]"
    run(["ffmpeg", "-y", "-nostdin", *http_opts(src_url),
         "-ss", f"{clip['start']:.2f}", "-i", src_url, *logo_inputs, "-t", f"{duration:.2f}",
         "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-maxrate", "2800k", "-bufsize", "5600k", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
         "-movflags", "+faststart", out_path])


# ---------------- email ----------------

def draft_steps(cfg: dict, attached: bool) -> str:
    attach_note = "" if attached else " (too big to attach: download it from the Actions run artifacts)"
    return f"""NEXT STEPS (this campaign needs draft approval)
1. Content Rewards -> {cfg['name']} campaign -> submit this video as a DRAFT{attach_note}.
2. When the draft is APPROVED: open the YouTube Studio link above -> Visibility -> Public.
3. Within 30 minutes, submit the YouTube Shorts link in Content Rewards.
If the draft is rejected: delete the private video in YouTube Studio."""


# ---------------- main ----------------

def main(campaign: str, state: dict | None = None, quiet_no_vod: bool = False) -> bool:
    """Makes today's clip(s) for one campaign. Returns True if a clip was made."""
    state = state if state is not None else load_state()
    cfg = all_campaigns(state)[campaign]
    tag = f"[{cfg['name']}]"
    if not cfg.get("enabled", True):
        print(f"{tag} campaign is paused/retired - nothing to do.")
        return False
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    vod = pick_vod(cfg, state)
    if not vod:
        print(f"{tag} no new VOD")
        if not quiet_no_vod:
            send_email(f"{tag} No new Kick VOD today",
                       f"No new usable {cfg['name']} VOD on kick.com/{cfg['kick_channel']} since the last run.")
        return False
    print(f"{tag} Clipping VOD: {vod['title']} ({vod['url']})")
    if cfg.get("logo") and not os.path.exists(cfg["logo"]["file"]):
        send_email(f"{tag} Logo file missing", f"Upload the logo to {cfg['logo']['file']} in the repo.")
        return False
    low_url, best_url = variant_urls(vod["source"])

    audio = load_audio(low_url)
    peaks = find_peaks(audio)
    candidates = transcribe_windows(audio, peaks, cfg["language"])
    del audio
    pb = load_playbook(campaign)
    if pb:
        print(f"{tag} Using playbook from {pb.get('updated')}: {pb.get('summary', '')[:200]}")
    clips = choose_clips(cfg, candidates, vod["title"], pb)

    state.setdefault("processed_vods", []).append(vod["uuid"])
    state["processed_vods"] = state["processed_vods"][-300:]
    save_state(state)

    if not clips:
        send_email(f"{tag} No usable clips today",
                   f"Claude found no rule-safe moments in: {vod['title']}\n{vod['url']}")
        return False

    tiktok_note = ""
    if "tiktok" in cfg.get("platforms", []) and os.environ.get("TIKTOK_SLOT_FREE") == "1":
        tiktok_note = ("\nTIKTOK: today's TikTok slot is free, so after it's live on YouTube you can also "
                       "post this same video on TikTok (caption below) and submit that link too.\n")

    for i, clip in enumerate(clips, 1):
        out = os.path.join(OUTPUT_DIR, f"{campaign}_{vod['uuid'][:8]}_{i}.mp4")
        print(f"Rendering clip {i}: {clip['start']:.0f}-{clip['end']:.0f}s - {clip['hook']}")
        style = {**DEFAULT_STYLE, **pb.get("style", {})}
        render_clip(best_url, clip, out, style, cfg.get("logo"))

        title = (clip["youtube_title"] or clip["hook"] or cfg["name"]) + cfg["title_suffix"]
        extra = [h for h in pb.get("hashtags", []) if h.lower() not in cfg["description"].lower()
                 and h.lower() not in title.lower()][:4]
        description = f"{clip['youtube_title']}\n\n{cfg['description'].replace('{channel}', vod.get('channel') or cfg.get('kick_channel') or '')}" + (
            " " + " ".join(extra) if extra else "")
        attached = os.path.getsize(out) < EMAIL_SAFE_BYTES
        info = (f"{cfg['name']} clip: {clip['hook']}\n"
                f"Source: {vod['url']} at {clip['start'] / 60:.1f} min "
                f"({clip['end'] - clip['start']:.0f}s)\nWhy: {clip['reason']}\n"
                f"YouTube title: {title}\n")

        if cfg["needs_approval"]:
            # campaign approves drafts first -> private upload now, you publish after approval
            video_id = None
            try:
                video_id = youtube_upload_private(out, title, description, cfg["tags"],
                                                  language=cfg["language"])
            except Exception as e:
                print(f"YouTube upload failed: {e}")
            if video_id:
                log_posted(state, {"campaign": campaign, "video_id": video_id,
                                   "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                                   "hook": clip["hook"], "title": title, "style": style,
                                   "length_s": round(clip["end"] - clip["start"])})
                save_state(state)
            yt = (f"YouTube (PRIVATE): https://studio.youtube.com/video/{video_id}/edit\n"
                  f"Link to submit once public: https://youtube.com/shorts/{video_id}\n"
                  if video_id else "YouTube upload FAILED - check the Actions log.\n")
            send_email(f"{tag} Clip ready for draft approval - {clip['hook']}",
                       f"{info}\n{yt}\n{draft_steps(cfg, attached)}\n", [out] if attached else [])
            continue

        # no draft approval -> nothing is posted until YOU approve (30-minute window starts then)
        pid, token = short_id(), new_token()
        state.setdefault("pending", {})[pid] = {
            "token": token, "campaign": campaign, "file": os.path.basename(out),
            "run_id": os.environ.get("GITHUB_RUN_ID", ""), "title": title,
            "description": description, "tags": cfg["tags"], "language": cfg["language"],
            "hook": clip["hook"], "style": style, "length_s": round(clip["end"] - clip["start"]),
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        save_state(state)
        body = f"""{info}{tiktok_note}
NOTHING HAS BEEN POSTED YET.
When you have 30 minutes free, approve it: it goes live on YouTube within ~2 minutes
and you get a "LIVE NOW" email with the link to submit in Content Rewards.

{approve_block("publish", pid, token, "APPROVE & POST NOW")}

Don't like it? Just ignore this email - it is never posted. The approval expires after 6 days.
"""
        send_email(f"{tag} Approve to post: {clip['hook']}", body, [out] if attached else [])
    return True


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tjr")
