"""
Shared helpers for the clipping pipelines (Bichou + Tokyo Girl):
Claude JSON calls, ASS subtitle writing, FFmpeg helpers, private YouTube
uploads, Gmail delivery and the small state file that remembers which
Kick VODs were already clipped.
"""

import os
import re
import json
import smtplib
import subprocess
from email.message import EmailMessage

STATE_PATH = os.environ.get("CLIPS_STATE_PATH", "state/clips_state.json")
OUTPUT_DIR = os.environ.get("CLIPS_OUTPUT_DIR", "clips_output")
FONT_NAME = "DejaVu Sans"
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")


# ---------- state ----------

def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"processed_vods": [], "tokyo_girl_history": []}


def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ---------- Claude ----------

def ask_claude_json(system: str, user: str, max_tokens: int = 4000) -> dict | list:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = resp.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    # tolerate a sentence before/after the JSON
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=0)
    end = max(text.rfind("}"), text.rfind("]")) + 1
    return json.loads(text[start:end])


def ask_claude_json_blocks(system: str, content: list[dict], max_tokens: int = 4000) -> dict | list:
    """Like ask_claude_json, but content is a list of Anthropic content blocks (text + images)."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(model=CLAUDE_MODEL, max_tokens=max_tokens, system=system,
                                  messages=[{"role": "user", "content": content}])
    text = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=0)
    end = max(text.rfind("}"), text.rfind("]")) + 1
    return json.loads(text[start:end])


# ---------- playbooks (written by research.py, read by the editors) ----------

PLAYBOOK_DIR = os.environ.get("PLAYBOOK_DIR", "state")


def playbook_path(campaign: str) -> str:
    return os.path.join(PLAYBOOK_DIR, f"playbook_{campaign}.json")


def load_playbook(campaign: str) -> dict:
    try:
        with open(playbook_path(campaign)) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def playbook_prompt(pb: dict) -> str:
    """Turns a playbook into prompt text for the editor."""
    if not pb:
        return ""
    lines = ["", "WHAT IS WORKING RIGHT NOW (learned from this campaign's top clips and",
             f"trending Shorts, updated {pb.get('updated', '?')}). Follow these patterns,",
             "but never copy another creator's text word for word. Campaign rules above",
             "always win over trends.",
             f"- Summary: {pb.get('summary', '')}"]
    for key, label in [("moments_to_pick", "Moments that perform"),
                       ("hook_examples", "Hook style examples"),
                       ("avoid", "Avoid")]:
        if pb.get(key):
            lines.append(f"- {label}: " + " | ".join(pb[key][:6]))
    for key, label in [("title_formula", "Title formula"), ("caption_formula", "Caption formula"),
                       ("experiment", "This cycle's experiment (try it on one clip)")]:
        if pb.get(key):
            lines.append(f"- {label}: {pb[key]}")
    return "\n".join(lines)


def log_posted(state: dict, entry: dict):
    """Remembers what we posted (and how) so research.py can learn from our own results."""
    state.setdefault("posted", []).append(entry)
    state["posted"] = state["posted"][-200:]


# ---------- text cleaning ----------

CURRENCY_WORDS = {"€": " euros", "$": " dollars", "£": " livres", "¥": " yens"}


def remove_currency_symbols(text: str) -> str:
    """Campaign rule: no currency symbols may appear in the video."""
    for sym, word in CURRENCY_WORDS.items():
        # "500€" / "€500" / "$ 500" -> "500 euros"
        text = re.sub(rf"\{sym}\s*(\d+(?:[ .,]\d+)*)", lambda m: m.group(1) + word, text)
        text = re.sub(rf"(\d+(?:[ .,]\d+)*)\s*\{sym}", lambda m: m.group(1) + word, text)
        text = text.replace(sym, word)
    return re.sub(r"\s{2,}", " ", text).strip()


def strip_emoji(text: str) -> str:
    return re.sub(
        "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF️]+",
        "", text,
    ).strip()


# ---------- ASS subtitles ----------

def _ass_time(t: float) -> str:
    t = max(t, 0)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def write_ass(path: str, title: str | None, subs: list[dict], duration: float,
              sub_y: int = 1450, title_y: int = 260, sub_size: int = 68, title_size: int = 74):
    """
    subs: [{"start": s, "end": s, "text": "..."}] relative to the clip.
    Styles: big white-on-black-outline captions; yellow title at the top.
    """
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{FONT_NAME},{sub_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,8,70,70,{sub_y},1
Style: Title,{FONT_NAME},{title_size},&H0000E5FF,&H0000E5FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,2,8,60,60,{title_y},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    if title:
        lines.append(
            f"Dialogue: 1,{_ass_time(0)},{_ass_time(duration)},Title,,0,0,0,,{_ass_escape(title)}\n"
        )
    for s in subs:
        lines.append(
            f"Dialogue: 0,{_ass_time(s['start'])},{_ass_time(s['end'])},Sub,,0,0,0,,{_ass_escape(s['text'])}\n"
        )
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def ffmpeg_filter_path(path: str) -> str:
    """Escape a file path for use inside an FFmpeg filter argument."""
    return os.path.abspath(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def run(cmd: list[str], **kw):
    """Run a command; on failure print the tail of stderr so the Actions log is useful."""
    result = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if result.returncode != 0:
        print("COMMAND FAILED:", " ".join(cmd[:6]), "...")
        print(result.stderr[-3000:])
        raise RuntimeError(f"{cmd[0]} exited with {result.returncode}")
    return result


# ---------- YouTube ----------

def youtube_upload_private(video_path: str, title: str, description: str,
                           tags: list[str], language: str = "fr",
                           publish_at: str | None = None) -> str:
    """Uploads as PRIVATE. With publish_at (RFC 3339, UTC), YouTube makes it
    public by itself at that time. Returns the video id."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": tags[:15],
            "categoryId": "20",  # Gaming
            "defaultLanguage": language,
            "defaultAudioLanguage": language,
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
        },
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    response = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    return response["id"]


# ---------- email ----------

def send_email(subject: str, body: str, attachments: list[str] | None = None):
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    to = os.environ.get("EMAIL_TO", sender)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)
    for path in attachments or []:
        with open(path, "rb") as f:
            msg.add_attachment(f.read(), maintype="video", subtype="mp4",
                               filename=os.path.basename(path))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
    print(f"Email sent: {subject}")


EMAIL_SAFE_BYTES = 18 * 1024 * 1024  # Gmail's 25MB limit, minus base64 overhead


def next_publish_time(uk_time: str) -> tuple[str, str]:
    """Next occurrence of HH:MM UK time -> (RFC 3339 UTC for YouTube, readable UK label)."""
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    uk = ZoneInfo("Europe/London")
    hh, mm = (int(x) for x in uk_time.split(":"))
    now = datetime.now(uk)
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target < now + timedelta(minutes=20):
        target += timedelta(days=1)
    utc = target.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return utc, target.strftime("%a %d %b at %H:%M") + " UK time"
