"""
One-click approvals, run by .github/workflows/approvals.yml.

  python approvals.py locate     -> finds the pending clip's run/file (for the artifact download)
  python approvals.py publish    -> posts an approved clip to YouTube as PUBLIC right now,
                                    then emails you the link to submit within 30 minutes
  python approvals.py activate   -> switches on a campaign the scout recommended

Env: ITEM_ID, ITEM_TOKEN (from the email link), MANUAL=true when you ran it
yourself from the Actions tab (no token needed then - only you can do that).
"""

import os
import sys
import glob
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from common import load_state, save_state, youtube_upload_private, send_email, log_posted  # noqa: E402
from campaigns import all_campaigns  # noqa: E402

ITEM = os.environ.get("ITEM_ID", "").strip()
TOKEN = os.environ.get("ITEM_TOKEN", "").strip()
MANUAL = os.environ.get("MANUAL", "").lower() == "true"
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "downloaded")


def authorised(entry: dict) -> bool:
    return MANUAL or (TOKEN and TOKEN == entry.get("token"))


def locate():
    state = load_state()
    entry = state.get("pending", {}).get(ITEM)
    out = os.environ.get("GITHUB_OUTPUT")
    if not entry or not authorised(entry):
        print(f"No pending clip '{ITEM}' (or wrong link) - nothing to download.")
        return
    print(f"Clip {ITEM}: run {entry['run_id']}, file {entry['file']}")
    if out:
        with open(out, "a") as f:
            f.write(f"run_id={entry['run_id']}\nfile={entry['file']}\n")


def publish():
    state = load_state()
    entry = state.get("pending", {}).get(ITEM)
    if not entry:
        send_email(f"[Approve] Clip {ITEM} not found",
                   "That clip was already posted, expired (6 days), or the link is wrong. Nothing was posted.")
        return
    if not authorised(entry):
        print("Token mismatch - refusing to publish.")
        return
    path = os.path.join(DOWNLOAD_DIR, entry["file"])
    if not os.path.exists(path):
        found = glob.glob(os.path.join(DOWNLOAD_DIR, "**", entry["file"]), recursive=True)
        path = found[0] if found else path
    if not os.path.exists(path):
        send_email(f"[Approve] Couldn't find the video for {ITEM}",
                   "The stored video has expired or failed to download, so nothing was posted. "
                   "Check the Approvals run log in GitHub Actions.")
        return

    camp = all_campaigns(state).get(entry["campaign"], {})
    name = camp.get("name", entry["campaign"])
    video_id = youtube_upload_private(path, entry["title"], entry["description"], entry["tags"],
                                      language=entry.get("language", "en"), privacy="public")
    print(f"Published: https://youtube.com/shorts/{video_id}")
    now = datetime.now(timezone.utc)
    log_posted(state, {"campaign": entry["campaign"], "video_id": video_id,
                       "date": now.strftime("%Y-%m-%d"), "hook": entry["hook"],
                       "title": entry["title"], "style": entry.get("style"),
                       "length_s": entry.get("length_s")})
    del state["pending"][ITEM]
    save_state(state)

    cr = (f"https://contentrewards.com/c/campaigns/{camp['content_rewards_id']}"
          if camp.get("content_rewards_id") else "Content Rewards")
    send_email(
        f"[{name}] LIVE NOW - submit within 30 minutes",
        f"""It's live: https://youtube.com/shorts/{video_id}

SUBMIT THIS LINK NOW (within 30 minutes of {now.strftime('%H:%M')} UTC):
{cr} -> Submit clip -> paste: https://youtube.com/shorts/{video_id}

Posted: {entry['title']}
""")


def activate():
    state = load_state()
    cand = state.get("candidates", {}).get(ITEM)
    if not cand:
        send_email(f"[Scout] Campaign {ITEM} not found", "It was already activated, expired, or the link is wrong.")
        return
    if not authorised(cand):
        print("Token mismatch - refusing to activate.")
        return
    slug, config = cand["slug"], cand["config"]
    state.setdefault("active_campaigns", {})[slug] = config
    if slug in state.get("retired", []):
        state["retired"].remove(slug)
    del state["candidates"][ITEM]
    save_state(state)
    send_email(f"[Scout] {config['name']} is now active",
               f"""The agent will start making videos for {config['name']} from the next daily run.

Source: kick.com/{config['kick_channel']}  |  Rate: ${config.get('rate', '?')}/1K views
Rules it will follow:
{config['rules']}

Make sure you've joined the campaign and linked your channel:
https://contentrewards.com/c/campaigns/{config['content_rewards_id']}
To switch it off: GitHub -> state/clips_state.json -> active_campaigns -> set "enabled": false.
""")


if __name__ == "__main__":
    {"locate": locate, "publish": publish, "activate": activate}[sys.argv[1]]()
