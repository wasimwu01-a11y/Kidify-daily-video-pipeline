"""
Daily planner: ONE YouTube video per day, for the best active campaign.

Picks among enabled, non-retired Kick campaigns that allow YouTube:
the one used least recently, then the best rate. If that streamer has no new
stream, it tries the next campaign, so the daily slot isn't wasted.
FORCE_CAMPAIGN=<slug> makes it use that campaign only.
(TikTok's one-a-day is the Tokyo Girl edit; if that campaign is retired, the
YouTube clip's email tells you to post the same clip on TikTok, when allowed.)
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from common import load_state, save_state, send_email  # noqa: E402
from campaigns import all_campaigns  # noqa: E402
import kick_clipper  # noqa: E402


def expire_pending(state: dict):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=6)).strftime("%Y-%m-%d")
    pend = state.get("pending", {})
    for k in [k for k, v in pend.items() if v.get("created", "") < cutoff]:
        del pend[k]


def main():
    state = load_state()
    expire_pending(state)
    save_state(state)
    camps = all_campaigns(state)
    eligible = [k for k, c in camps.items()
                if c.get("enabled", True) and (c.get("kick_channel") or c.get("kick_category"))
                and "youtube" in c.get("platforms", ["youtube"])]
    forced = os.environ.get("FORCE_CAMPAIGN", "").strip()
    if forced:
        eligible = [forced] if forced in camps else []
    if not eligible:
        send_email("[Daily] No active YouTube campaign",
                   "All campaigns are paused or retired. Check the scout emails and activate a new one.")
        return
    last = state.get("last_used", {})
    eligible.sort(key=lambda k: (last.get(k, ""), -(camps[k].get("rate") or 0)))
    print("Order today:", eligible)
    if "tokyo_girl" in state.get("retired", []):
        os.environ["TIKTOK_SLOT_FREE"] = "1"

    for slug in eligible:
        made = kick_clipper.main(slug, state, quiet_no_vod=True)
        if made:
            state.setdefault("last_used", {})[slug] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            save_state(state)
            print(f"Today's YouTube video: {slug}")
            return
    send_email("[Daily] No new streams today",
               "None of your active campaigns' streamers had a new usable stream: "
               + ", ".join(camps[k]["name"] for k in eligible))


if __name__ == "__main__":
    main()
