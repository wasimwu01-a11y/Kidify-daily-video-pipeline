"""
Bichou (ZK CLIPPING) - "Spécial Miami & GTA 6" campaign.

Daily flow:
  1. Find Bichou's newest Kick VOD we haven't clipped yet (kick.com/bichouu
     is the ONLY allowed source). Skips VODs whose title looks like casino.
  2. Decode its audio (lowest quality stream = small download), score every
     second by loudness spikes vs. the surrounding baseline, keep the best
     ~12 moments.
  3. Transcribe those moments in French with faster-whisper (free, CPU).
  4. Claude picks up to CLIPS_PER_DAY clips (30-55 s), rejects anything
     casino/gambling, and returns spelling-corrected French subtitles.
  5. FFmpeg renders 1080x1920: blurred background + full stream frame in the
     middle, hook title on top, French subtitles below. No currency symbols.
  6. Uploads each clip to YouTube as PRIVATE (campaign drafts need approval
     before posting) and emails it to you with next steps.

Campaign rules enforced in code: source = Kick only, >= 30 s, French
subtitles, no casino, no currency symbols. "Link in bio" is a one-time
manual step on the channel.
"""

import os
import re
import sys
import json
import subprocess
from urllib.parse import urljoin

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from common import (  # noqa: E402
    OUTPUT_DIR, load_state, save_state, ask_claude_json, remove_currency_symbols,
    strip_emoji, write_ass, ffmpeg_filter_path, run, youtube_upload_private,
    send_email, EMAIL_SAFE_BYTES,
)

KICK_CHANNEL = "bichouu"
CLIPS_PER_DAY = int(os.environ.get("CLIPS_PER_DAY", "3"))
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
MAX_ANALYSE_SECONDS = int(os.environ.get("MAX_ANALYSE_SECONDS", str(4 * 3600)))
MIN_CLIP, MAX_CLIP = 32.0, 55.0          # campaign minimum is 30 s; keep margin
N_CANDIDATES = 12
WINDOW_BEFORE, WINDOW_AFTER = 50, 30      # seconds of context around a peak
SR = 16000
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

CASINO_WORDS = re.compile(
    r"casino|slot|machine[s]? à sous|gambl|roobet|stake\.|stake |pari[s]? |bet |betting|"
    r"blackjack|roulette|poker|crash game|plinko", re.I)


# ---------------- Kick ----------------

def kick_get(url: str):
    """Kick's API sits behind Cloudflare; curl_cffi impersonates a real browser."""
    from curl_cffi import requests as creq
    r = creq.get(url, impersonate="chrome", timeout=30)
    r.raise_for_status()
    return r.json()


def list_vods() -> list[dict]:
    data = kick_get(f"https://kick.com/api/v2/channels/{KICK_CHANNEL}/videos")
    if isinstance(data, dict):
        data = data.get("data") or data.get("videos") or []
    vods = []
    for item in data:
        video = item.get("video") or {}
        uuid = video.get("uuid") or item.get("uuid") or str(item.get("id"))
        vods.append({
            "uuid": uuid,
            "title": item.get("session_title") or video.get("title") or "",
            "created_at": item.get("created_at") or video.get("created_at") or "",
            "duration_s": (item.get("duration") or 0) / 1000,
            "source": item.get("source") or video.get("source"),
            "url": f"https://kick.com/{KICK_CHANNEL}/videos/{uuid}",
        })
    return vods


def vod_from_url(url: str) -> dict:
    """Manual override: VOD_URL can be a kick.com/.../videos/<uuid> link or an .m3u8."""
    if ".m3u8" in url:
        return {"uuid": url.split("/")[-2], "title": "manual", "duration_s": 0,
                "source": url, "url": url}
    uuid = url.rstrip("/").split("/")[-1]
    data = kick_get(f"https://kick.com/api/v1/video/{uuid}")
    return {"uuid": uuid, "title": (data.get("livestream") or {}).get("session_title", ""),
            "duration_s": 0, "source": data["source"], "url": url}


def pick_vod(state: dict) -> dict | None:
    manual = os.environ.get("VOD_URL", "").strip()
    if manual:
        return vod_from_url(manual)
    done = set(state.get("processed_vods", []))
    for vod in list_vods():  # newest first
        if vod["uuid"] in done or not vod["source"]:
            continue
        if CASINO_WORDS.search(vod["title"]):
            print(f"Skipping casino-looking VOD: {vod['title']}")
            continue
        if vod["duration_s"] and vod["duration_s"] < 15 * 60:
            continue
        return vod
    return None


def variant_urls(master_url: str) -> tuple[str, str]:
    """Returns (lowest-quality URL for audio analysis, best <=1080p URL for clips)."""
    import requests
    text = requests.get(master_url, headers={"User-Agent": UA}, timeout=30).text
    if "#EXT-X-STREAM-INF" not in text:
        return master_url, master_url
    variants = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            m = re.search(r"RESOLUTION=(\d+)x(\d+)", line)
            height = int(m.group(2)) if m else 0
            uri = lines[i + 1].strip()
            variants.append((height, urljoin(master_url, uri)))
    variants.sort()
    best = [v for v in variants if v[0] <= 1080] or variants
    return variants[0][1], best[-1][1]


# ---------------- moment finding ----------------

def http_opts(url: str) -> list[str]:
    """-user_agent is only valid for network inputs, not local files."""
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
    # baseline = rolling median over 5 minutes, so a loud segment of a loud
    # stream doesn't win just for being loud overall
    half = 150
    baseline = np.array([np.median(smooth[max(0, i - half): i + half]) for i in range(0, secs, 10)])
    baseline = np.repeat(baseline, 10)[:secs]
    score = smooth - baseline
    score[: 120] = -99   # skip stream start-up
    score[-60:] = -99
    peaks = []
    for idx in np.argsort(score)[::-1]:
        if len(peaks) >= N_CANDIDATES:
            break
        if score[idx] < -50:
            break
        if all(abs(int(idx) - p) > 120 for p in peaks):
            peaks.append(int(idx))
    return sorted(peaks)


def transcribe_windows(audio: np.ndarray, peaks: list[int]) -> list[dict]:
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    total = len(audio) / SR
    candidates = []
    for n, p in enumerate(peaks):
        start = max(0, p - WINDOW_BEFORE)
        end = min(total, p + WINDOW_AFTER)
        chunk = audio[int(start * SR): int(end * SR)]
        segments, _ = model.transcribe(chunk, language="fr", vad_filter=True, beam_size=5)
        segs = [{"start": round(start + s.start, 2), "end": round(start + s.end, 2),
                 "text": s.text.strip()} for s in segments if s.text.strip()]
        print(f"Candidate {n}: {start:.0f}-{end:.0f}s, {len(segs)} segments")
        candidates.append({"candidate": n, "window_start": round(start, 2),
                           "window_end": round(end, 2), "peak": p, "segments": segs})
    return candidates


# ---------------- Claude selection ----------------

SYSTEM = f"""Tu es monteur pour une campagne de clipping du streamer français Bichou
("Spécial Miami & GTA 6"). Tu reçois des moments candidats d'un live Kick,
avec leur transcription automatique (Whisper, horodatée en secondes absolues).

Choisis jusqu'à {CLIPS_PER_DAY} clips qui feront le plus de vues en format court.

Règles de la campagne (obligatoires) :
- Thèmes autorisés : lifestyle, aventures IRL à Miami, GTA 6, voyages, voitures
  de luxe, humour, réactions, moments marquants.
- ZÉRO casino : rejette tout moment qui parle de casino, jeux d'argent, paris,
  machines à sous, ou de plateformes de gambling.
- Durée de chaque clip : entre {MIN_CLIP:.0f} et {MAX_CLIP:.0f} secondes, à
  l'intérieur de la fenêtre du candidat. Commence juste avant l'action, finis
  sur la chute ou la réaction.
- Sous-titres en français obligatoires : lisibles, synchronisés, SANS FAUTE.
  Corrige l'orthographe, la grammaire et les mots mal reconnus par Whisper.
  Garde les horodatages de Whisper, mais découpe en phrases courtes
  (max 2 lignes, ~38 caractères par ligne).
- AUCUN symbole monétaire (€, $, £...) nulle part : écris "euros", "dollars".
- Pas d'emoji.
- Si aucun moment n'est assez bon ou conforme, renvoie une liste vide.

Réponds UNIQUEMENT en JSON :
{{"clips": [{{
  "candidate": 0,
  "start": 1234.5,
  "end": 1275.0,
  "hook": "titre accrocheur affiché en haut (max 40 caractères)",
  "youtube_title": "titre YouTube en français (max 80 caractères)",
  "reason": "pourquoi ce moment va marcher",
  "subtitles": [{{"start": 1234.6, "end": 1237.1, "text": "..."}}]
}}]}}"""


def choose_clips(candidates: list[dict], vod_title: str) -> list[dict]:
    usable = [c for c in candidates if len(c["segments"]) >= 3]
    if not usable:
        return []
    user = (f"Titre du live : {vod_title}\n\nCandidats :\n"
            + json.dumps(usable, ensure_ascii=False))
    result = ask_claude_json(SYSTEM, user, max_tokens=8000)
    clips = result.get("clips", []) if isinstance(result, dict) else result
    by_id = {c["candidate"]: c for c in candidates}
    valid = []
    for clip in clips[:CLIPS_PER_DAY]:
        cand = by_id.get(clip.get("candidate"))
        if cand is None:
            continue
        start = max(float(clip["start"]), cand["window_start"])
        end = min(float(clip["end"]), cand["window_end"])
        if end - start < MIN_CLIP:  # stretch to the minimum inside the window
            end = min(cand["window_end"], start + MIN_CLIP)
            start = max(cand["window_start"], end - MIN_CLIP)
        if end - start < 30.5:
            print(f"Dropping candidate {cand['candidate']}: too short ({end - start:.1f}s)")
            continue
        end = min(end, start + MAX_CLIP)
        subs = []
        for s in clip.get("subtitles", []):
            text = strip_emoji(remove_currency_symbols(str(s.get("text", ""))))
            rs, re_ = float(s["start"]) - start, float(s["end"]) - start
            if text and re_ > 0 and rs < end - start:
                subs.append({"start": max(rs, 0), "end": min(re_, end - start), "text": text})
        if not subs:
            print(f"Dropping candidate {cand['candidate']}: no subtitles")
            continue
        valid.append({
            "start": start, "end": end, "subs": subs,
            "hook": strip_emoji(remove_currency_symbols(clip.get("hook", "")))[:45],
            "youtube_title": strip_emoji(remove_currency_symbols(clip.get("youtube_title", "")))[:85],
            "reason": clip.get("reason", ""),
        })
    return valid


# ---------------- render ----------------

def render_clip(src_url: str, clip: dict, out_path: str):
    duration = clip["end"] - clip["start"]
    ass_path = out_path.replace(".mp4", ".ass")
    # stream frame is 1080x608 centred (y 656-1264): hook above, subs below
    write_ass(ass_path, clip["hook"], clip["subs"], duration, sub_y=1310, title_y=430)
    vf = (
        "[0:v]split[a][b];"
        "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "boxblur=20:2,eq=brightness=-0.12[bg];"
        "[b]scale=1080:-2[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,ass='{ffmpeg_filter_path(ass_path)}',fps=30[v]"
    )
    run(["ffmpeg", "-y", "-nostdin", *http_opts(src_url),
         "-ss", f"{clip['start']:.2f}", "-i", src_url, "-t", f"{duration:.2f}",
         "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-maxrate", "2800k", "-bufsize", "5600k", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
         "-movflags", "+faststart", out_path])


# ---------------- main ----------------

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    state = load_state()
    vod = pick_vod(state)
    if not vod:
        send_email("[Bichou] No new Kick VOD today",
                   "No new (non-casino) Bichou VOD since the last run, so no clips today.")
        return
    print(f"Clipping VOD: {vod['title']} ({vod['url']})")
    low_url, best_url = variant_urls(vod["source"])

    audio = load_audio(low_url)
    peaks = find_peaks(audio)
    candidates = transcribe_windows(audio, peaks)
    del audio
    clips = choose_clips(candidates, vod["title"])

    state.setdefault("processed_vods", []).append(vod["uuid"])
    state["processed_vods"] = state["processed_vods"][-200:]
    save_state(state)

    if not clips:
        send_email("[Bichou] No usable clips today",
                   f"Claude found no campaign-safe moments in: {vod['title']}\n{vod['url']}")
        return

    for i, clip in enumerate(clips, 1):
        out = os.path.join(OUTPUT_DIR, f"bichou_{vod['uuid'][:8]}_{i}.mp4")
        print(f"Rendering clip {i}: {clip['start']:.0f}-{clip['end']:.0f}s - {clip['hook']}")
        render_clip(best_url, clip, out)

        title = (clip["youtube_title"] or clip["hook"] or "Bichou à Miami") + " #Shorts"
        description = (f"{clip['youtube_title']}\n\nExtrait du live Kick de Bichou : "
                       f"https://kick.com/{KICK_CHANNEL}\n\n#bichou #miami #gta6 #shorts")
        video_id = None
        try:
            video_id = youtube_upload_private(out, title, description,
                                              ["bichou", "miami", "gta 6", "kick", "streamer"])
            print(f"Uploaded privately: {video_id}")
        except Exception as e:  # still email the clip if YouTube fails
            print(f"YouTube upload failed: {e}")

        attach = [out] if os.path.getsize(out) < EMAIL_SAFE_BYTES else []
        yt_lines = (
            f"YouTube (PRIVATE for now): https://studio.youtube.com/video/{video_id}/edit\n"
            f"Link to submit once public: https://youtube.com/shorts/{video_id}\n"
            if video_id else "YouTube upload FAILED - check the Actions log. Post it manually.\n")
        body = f"""Bichou clip {i}/{len(clips)}: {clip['hook']}
Source: {vod['url']} at {clip['start'] / 60:.1f} min ({clip['end'] - clip['start']:.0f}s)
Why: {clip['reason']}

{yt_lines}
NEXT STEPS
1. Content Rewards -> Bichou campaign -> submit this video as a DRAFT (attached{'' if attach else ' - too big to attach, download it from the Actions run artifacts'}).
2. When the draft is APPROVED: open the YouTube Studio link above -> Visibility -> Public.
3. Within 30 minutes, submit the YouTube Shorts link in Content Rewards.
If the draft is rejected: delete the private video in YouTube Studio.

Reminder: the campaign link must stay in the channel's description/bio.
"""
        send_email(f"[Bichou] Clip {i}/{len(clips)} ready for approval - {clip['hook']}", body, attach)


if __name__ == "__main__":
    main()
