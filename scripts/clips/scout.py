"""
Campaign scout - runs daily before the clipping.

  1. Reads the Content Rewards Discover list (budget left, % used, rate,
     platforms, category, description of ~100 clipping campaigns).
  2. Retires our active campaigns that are nearly out of budget
     (>= RETIRE_AT % used or < MIN_LEFT dollars left) and emails you.
  3. Shortlists new campaigns: pays per view, includes YouTube, healthy budget,
     no gambling. Reads each shortlisted campaign's full description and any
     rules page it links to.
  4. Claude ranks them for THIS channel and what the agent can clip
     automatically (streams on Kick), and drafts the editor's rules for each.
  5. Emails you up to 3 picks: join the campaign yourself (needs your login),
     then click the activate link - from the next daily run the agent makes
     videos for it (still one video per platform per day in total).
"""

import os
import re
import sys
import json
import html as htmllib
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from common import (  # noqa: E402
    load_state, save_state, ask_claude_json, send_email, approve_block, new_token, short_id,
)
from campaigns import all_campaigns, RESEARCH  # noqa: E402

DISCOVER_URLS = ["https://contentrewards.com/c/discover/clipping"]
RETIRE_AT = float(os.environ.get("RETIRE_AT_PERCENT", "95"))
MIN_LEFT = float(os.environ.get("RETIRE_BELOW_DOLLARS", "75"))
MIN_BUDGET = float(os.environ.get("SCOUT_MIN_BUDGET", "1000"))
MAX_PICKS = 3
GAMBLING = re.compile(r"casino|gambl|roobet|stake\.com|\bbet\b|betting|slots?\b|poker|blackjack|crypto casino", re.I)


# ---------------- Content Rewards data ----------------

def get(url: str) -> str:
    from curl_cffi import requests as creq
    r = creq.get(url, impersonate="chrome", timeout=40)
    r.raise_for_status()
    return r.text


def unescape_flight(text: str) -> str:
    return text.replace("\\\\", "\x00").replace('\\"', '"').replace("\x00", "\\")


def parse_campaigns(page: str) -> list[dict]:
    """Discover pages embed each campaign as a JSON object starting with "availableBudgetRaw"."""
    s = unescape_flight(page)
    dec = json.JSONDecoder()
    found = {}
    for m in re.finditer(r'\{"availableBudgetRaw":', s):
        try:
            obj, _ = dec.raw_decode(s[m.start():])
        except json.JSONDecodeError:
            continue
        if obj.get("id"):
            found[obj["id"]] = obj
    return list(found.values())


def find_object(s: str, campaign_id: str) -> dict | None:
    """The JSON object whose "id" is campaign_id (pages also list OTHER campaigns)."""
    dec = json.JSONDecoder()
    for m in re.finditer(rf'"id":"{re.escape(campaign_id)}"', s):
        start = m.start()
        for _ in range(400):  # walk back to each enclosing '{' and try it
            start = s.rfind("{", 0, start)
            if start == -1:
                break
            try:
                obj, _ = dec.raw_decode(s[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("id") == campaign_id and (
                    "progressPercentage" in obj or "availableBudgetRaw" in obj):
                return obj
    return None


def campaign_status(campaign_id: str) -> dict:
    """% used and budget left for one campaign, read from its own page."""
    s = unescape_flight(get(f"https://contentrewards.com/c/campaigns/{campaign_id}"))
    obj = find_object(s, campaign_id) or {}
    status = str(obj.get("status", "")).lower()
    return {"progress": obj.get("progressPercentage"), "left": obj.get("availableBudgetRaw"),
            "ended": status in ("ended", "completed", "archived")}


def page_text(url: str, limit: int = 3500) -> str:
    """Readable text of a rules page (best effort)."""
    try:
        raw = get(url)
    except Exception:
        return ""
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\s+", " ", text).strip()[:limit]


# ---------------- retirement ----------------

def retire_finished(state: dict, by_id: dict) -> list[str]:
    retired = []
    camps = all_campaigns(state)
    targets = {k: c.get("content_rewards_id") for k, c in camps.items() if c.get("enabled", True)}
    if "tokyo_girl" not in state.get("retired", []):
        targets["tokyo_girl"] = RESEARCH["tokyo_girl"]["content_rewards_id"]
    for slug, cid in targets.items():
        if not cid:
            continue
        info = by_id.get(cid)
        if info:
            status = {"progress": info.get("progressPercentage"), "left": info.get("availableBudgetRaw"),
                      "ended": False}
        else:
            try:
                status = campaign_status(cid)
            except Exception as e:
                print(f"[{slug}] status check failed: {e}")
                continue
        print(f"[{slug}] {status}")
        done = status["ended"] or (status["progress"] is not None and status["progress"] >= RETIRE_AT) \
            or (status["left"] is not None and status["left"] < MIN_LEFT)
        if done:
            state.setdefault("retired", []).append(slug)
            retired.append(f"{camps.get(slug, {}).get('name', slug)} "
                           f"({status['progress']}% used, ${status['left']} left)")
    return retired


# ---------------- recommending ----------------

SYSTEM = """You are the campaign scout for an automated clipping channel that earns
from Content Rewards campaigns (paid per 1,000 views).

What the agent can make AUTOMATICALLY: 20-55 second vertical clips with
subtitles, cut from a streamer's past streams on KICK (kick.com/<channel>).
It CANNOT download from YouTube, Twitch, Instagram, TikTok or Google Drive.
So a campaign is only automatable if its clips can come from a Kick channel
(the description/rules name a kick.com link or say the creator streams on Kick).

The channel: YouTube Shorts (+ TikTok posted by hand). Current/past niche:
GTA 6 content, streamer clips, and TJR (trading streamer). English audience
(UK/US). It posts ONE video per platform per day in total, so only recommend
campaigns that are clearly worth a daily slot.

Rank the candidates for this channel. Prefer: Kick-sourced, fits the niche
(gaming / GTA / big streamers), English, YouTube Shorts allowed, good rate,
lots of budget left, not crowded, no draft pre-approval (faster), no
gambling. Reject anything gambling-related, adult, misleading or that
requires a different language than English (unless clearly worth it).

Return ONLY JSON:
{"picks": [{
  "id": "campaign id",
  "short_name": "e.g. Lacy GTA 6",
  "why": "1-2 sentences: why it's worth a slot",
  "fit_score": 1-10,
  "kick_channel": "kick channel slug or null if not on Kick",
  "language": "en",
  "needs_draft_approval": false,
  "rules": "the editor's rules for this campaign: what to clip, musts and must-nots, required hashtags/credits, in the same style as a briefing to a video editor",
  "required_hashtags": ["#tag"],
  "title_suffix": " #tag #Shorts",
  "description_line": "credit line for the YouTube description, e.g. Clip from X's Kick stream: https://kick.com/x"
}],
 "manual_only": [{"id": "...", "short_name": "...", "why": "good but not on Kick"}]}
Max 3 picks, best first. Empty lists are fine."""


def shortlist(campaigns: list[dict], state: dict) -> list[dict]:
    camps = all_campaigns(state)
    known = {c.get("content_rewards_id") for c in camps.values()}
    known |= {c.get("content_rewards_id") for c in RESEARCH.values()}
    recent = {cid for cid, d in state.get("scout_seen", {}).items()
              if d >= (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")}
    out = []
    for c in campaigns:
        text = f"{c.get('title', '')} {c.get('description', '')} {c.get('brand', '')}"
        if c.get("id") in known or c.get("id") in recent:
            continue
        if c.get("type") != "cpm" or "youtube" not in (c.get("platforms") or []):
            continue
        if (c.get("availableBudgetRaw") or 0) < MIN_BUDGET or (c.get("progressPercentage") or 0) > 80:
            continue
        if GAMBLING.search(text) or (c.get("payoutSortRaw") or 0) < 0.4:
            continue
        out.append(c)
    out.sort(key=lambda c: -(c.get("payoutSortRaw", 0) * min(c.get("availableBudgetRaw", 0), 20000)))
    return out[:25]


def describe(c: dict, with_rules: bool) -> dict:
    d = {"id": c["id"], "title": c.get("title"), "brand": c.get("brand"), "category": c.get("category"),
         "rate_per_1k": c.get("payoutSortRaw"), "budget_left": c.get("availableBudgetRaw"),
         "budget_total": c.get("budgetTotalRaw"), "percent_used": c.get("progressPercentage"),
         "clippers": c.get("creatorCountRaw"), "platforms": c.get("platforms"),
         "requires_application": c.get("requiresApplication"),
         "description": (c.get("description") or "")[:900]}
    if with_rules:
        links = re.findall(r"https?://[^\s\"')]+", c.get("description") or "")
        rule_links = [u for u in links if not re.search(r"kick\.com|youtube|tiktok|instagram|twitter|x\.com", u)]
        if rule_links:
            d["rules_page_text"] = page_text(rule_links[0])
    return d


def main():
    state = load_state()
    campaigns = []
    for url in DISCOVER_URLS:
        try:
            campaigns += parse_campaigns(get(url))
        except Exception as e:
            print(f"Discover fetch failed ({url}): {e}")
    by_id = {c["id"]: c for c in campaigns}
    print(f"Discover: {len(by_id)} campaigns")

    retired = retire_finished(state, by_id)
    if retired:
        save_state(state)
        send_email("[Scout] Campaign(s) retired - budget nearly gone",
                   "The agent stopped making videos for:\n- " + "\n- ".join(retired)
                   + "\n\nIt will use your other active campaigns (and recommend new ones).")

    cands = shortlist(list(by_id.values()), state)
    print(f"Shortlist: {len(cands)}")
    if not cands:
        save_state(state)
        return
    detailed = [describe(c, i < 8) for i, c in enumerate(cands)]
    active = [c["name"] for c in all_campaigns(state).values() if c.get("enabled", True)]
    result = ask_claude_json(SYSTEM, f"Our active campaigns: {active}\n\nCandidates:\n"
                             + json.dumps(detailed, ensure_ascii=False), max_tokens=4000)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for c in cands:  # don't re-pitch the same shortlist for 14 days
        state.setdefault("scout_seen", {})[c["id"]] = today
    blocks = []
    for p in (result.get("picks") or [])[:MAX_PICKS]:
        c = by_id.get(p.get("id"))
        if not c or not p.get("kick_channel"):
            continue
        kick = str(p["kick_channel"]).strip().split("/")[-1].lower()
        slug = re.sub(r"[^a-z0-9]+", "_", (p.get("short_name") or c["title"]).lower()).strip("_")[:30]
        tags = [t if t.startswith("#") else f"#{t}" for t in p.get("required_hashtags", [])][:5]
        config = {
            "name": p.get("short_name") or c["title"][:40],
            "enabled": True,
            "kick_channel": kick,
            "language": p.get("language") or "en",
            "needs_approval": bool(p.get("needs_draft_approval")),
            "rules": p.get("rules", ""),
            "title_suffix": p.get("title_suffix") or (" " + " ".join(tags[:2]) + " #Shorts"),
            "description": (p.get("description_line") or f"Clip from kick.com/{kick}") + "\n\n" + " ".join(tags),
            "tags": [t.lstrip("#") for t in tags],
            "content_rewards_id": c["id"],
            "platforms": c.get("platforms", []),
            "rate": c.get("payoutSortRaw"),
            "youtube_query": p.get("short_name") or c["title"],
            "notes": c.get("description", "")[:300],
        }
        cid, token = short_id(), new_token()
        state.setdefault("candidates", {})[cid] = {"slug": slug, "config": config, "token": token,
                                                   "created": today}
        blocks.append(f"""### {config['name']}  ({p.get('fit_score', '?')}/10)
{c['title']} by {c.get('brand')}
Rate: ${c.get('payoutSortRaw')}/1K views | Budget left: ${c.get('availableBudgetRaw'):,.0f} of ${c.get('budgetTotalRaw'):,.0f} ({c.get('progressPercentage')}% used) | {c.get('creatorCountRaw')} clippers
Platforms: {', '.join(c.get('platforms', []))} | Source: kick.com/{kick}{' | NEEDS DRAFT APPROVAL' if config['needs_approval'] else ''}
Why: {p.get('why')}

1) Join it (needs your login): https://contentrewards.com/c/campaigns/{c['id']}
2) Then switch it on for the agent:
{approve_block('activate', cid, token, 'ACTIVATE THIS CAMPAIGN')}
""")
    manual = [f"- {m.get('short_name')}: {m.get('why')} (https://contentrewards.com/c/campaigns/{m.get('id')})"
              for m in (result.get("manual_only") or [])[:3]]
    state["candidates"] = {k: v for k, v in state.get("candidates", {}).items()
                           if v.get("created", today) >= (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")}
    save_state(state)
    if blocks:
        body = ("Campaigns worth a slot on your channel. The agent can clip these automatically "
                "(they stream on Kick). It still makes one video per platform per day in total - "
                "it rotates between your active campaigns, favouring the best paying.\n\n"
                + "\n".join(blocks))
        if manual:
            body += "\nGood campaigns it can't clip automatically (not on Kick):\n" + "\n".join(manual)
        send_email(f"[Scout] {len(blocks)} campaign(s) worth joining", body)
    else:
        print("No automatable picks today.")


if __name__ == "__main__":
    main()
