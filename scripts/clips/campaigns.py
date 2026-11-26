"""
One entry per Kick-based clipping campaign. kick_clipper.py reads these.
To add a campaign: copy a block, change the Kick channel, rules and hashtags,
add a step for it in .github/workflows/daily-clips.yml, and add its
Content Rewards id to RESEARCH below. Every active campaign then gets the
same behaviour automatically: trend research + playbook every 3 days, and
(if it needs no draft approval) auto-posting at PUBLISH_TIME_UK.
"""

CAMPAIGNS = {
    # ---------------- Bichou (ZK CLIPPING) ----------------
    "bichou": {
        "name": "Bichou",
        "enabled": False,            # PAUSED: campaign ended. Set True to resume.
        "content_rewards_id": "ceff4682-947e-40c9-b7df-81a806c89943",
        "platforms": ["instagram", "tiktok", "youtube", "x"],
        "rate": 1.00,
        "kick_channel": "bichouu",
        "language": "fr",
        "clips_per_day": 1,
        "min_clip": 32.0,            # campaign minimum is 30 s
        "max_clip": 55.0,
        "needs_approval": True,      # "Drafts require pre-approval before posting"
        "no_currency_symbols": True,
        "skip_title": r"casino|slot|gambl|roobet|stake|\bpari|\bbet\b|blackjack|roulette|poker",
        "prefer_title": r"miami|irl|gta ?6|gta ?vi|usa|voyage|road ?trip",
        "title_suffix": " #Shorts",
        "description": "Extrait du live Kick de Bichou : https://kick.com/bichouu\n\n#bichou #miami #gta6 #shorts",
        "tags": ["bichou", "miami", "gta 6", "kick", "streamer"],
        "rules": """Tu es monteur pour la campagne de clipping du streamer français Bichou
("Spécial Miami & GTA 6"). Règles obligatoires :
- Thèmes autorisés : lifestyle, aventures IRL à Miami, GTA 6, voyages, voitures
  de luxe, humour, réactions, moments marquants.
- ZÉRO casino : rejette tout moment qui parle de casino, jeux d'argent, paris,
  machines à sous ou plateformes de gambling.
- Sous-titres en français obligatoires : lisibles, synchronisés, SANS FAUTE.
  Corrige l'orthographe, la grammaire et les mots mal reconnus par Whisper.
- AUCUN symbole monétaire (€, $, £...) : écris "euros", "dollars".
- "hook" et "youtube_title" en français.""",
    },

    # ---------------- ClipUp GTA VI logo campaign ----------------
    "clipup": {
        "name": "ClipUp GTA 6",
        "enabled": True,
        "content_rewards_id": "802cf95a-ea84-4070-9a96-8a917831cb16",
        "platforms": ["instagram", "tiktok", "youtube"],
        "rate": 0.25,                 # Tier 1 views only (US/UK/CA/AU)
        # no fixed streamer: each day it finds ENGLISH streamers playing GTA VI on Kick.
        # To limit it to streamers you choose, list them here, e.g. ["kaneljoseph", "gattouz0"]
        "kick_channel": None,
        "kick_category": "grand-theft-auto-vi",
        "kick_language": "English",
        "kick_channels": [],
        "require_title": r"gta ?(6|vi)|grand theft auto vi",
        "language": "en",
        "clips_per_day": 1,
        "min_clip": 20.0,
        "max_clip": 50.0,
        "needs_approval": False,
        "no_currency_symbols": False,
        "skip_title": r"casino|slot|gambl|roobet|stake\b",
        "prefer_title": r"",
        "title_suffix": " #gta6 #Clipup #Shorts",
        "description": "GTA 6 gameplay from {channel}'s Kick stream: https://kick.com/{channel}\n\n#gta6 #Clipup #GTAVI #shorts",
        "tags": ["gta6", "Clipup", "GTA 6", "GTA VI", "gameplay"],
        # the ClipUp logo must be on screen for the WHOLE clip, never covered, stretched or recoloured
        "logo": {"file": "assets/clipup/Hire Clippers — 1B+ Views Generated (1).png", "width": 780},
        "rules": """You are an editor for the ClipUp GTA 6 logo campaign.
Mandatory rules:
- Clip GTA 6 GAMEPLAY moments only: chaotic, funny or crazy things happening
  in the game, big reactions WHILE PLAYING, wild police chases, glitches,
  heists, first impressions of the map. Skip just-chatting, menus, loading
  screens, breaks and anything not showing the game.
- English only. Never portray the streamer negatively.
- Skip gambling/casino talk.
- English subtitles, clean and correctly spelled (fix game terms: Vice City,
  Leonida, Jason, Lucia, wanted level).
- "hook" and "youtube_title" in English; make clear it's GTA 6.""",
    },

    # ---------------- TJR (Reach) ----------------
    "tjr": {
        "name": "TJR",
        "enabled": True,
        "content_rewards_id": "33c3d5a9-84a9-40c8-b6e4-9904e4816339",
        "platforms": ["instagram", "tiktok", "youtube"],
        "rate": 0.75,
        "kick_channel": "tjr",
        "language": "en",
        "clips_per_day": 1,
        "min_clip": 20.0,
        "max_clip": 55.0,
        "needs_approval": False,     # post, then submit within 30 min; paid after 5,000 views
        "auto_publish": True,        # YouTube makes it public by itself at PUBLISH_TIME_UK
        "no_currency_symbols": False,
        "skip_title": r"casino|slot|gambl|roobet|stake\b",
        "prefer_title": r"",
        "title_suffix": " #TJR #Shorts",
        "description": "Clip from TJR's Kick stream: https://kick.com/tjr\n\n#TJR #trading #daytrading #stocks #shorts",
        "tags": ["TJR", "TJR Trades", "trading", "day trading", "stocks"],
        "rules": """You are an editor for the TJR (day trader / streamer) clipping campaign.
Mandatory rules:
- Pick funny moments, memorable quotes, big reactions and memorable moments
  featuring TJR. TJR must be the focus of the clip.
- NEVER portray TJR in a negative light (no mocking him, no clips of him
  losing his temper at someone, no out-of-context embarrassing moments).
- Skip gambling/casino talk.
- English subtitles: clean, correctly spelled, faithful to what is said.
  Fix Whisper's mistakes (tickers, trading terms: SPY, QQQ, NQ, ES, calls, puts).
- Audience is US/UK/CA/AU: plain English, no foreign slang.
- "hook" and "youtube_title" in English, curiosity-driven but not clickbait lies.""",
    },
}


# ---------------- Trend research targets (research.py) ----------------
# content_rewards_id = the id at the end of the campaign's Content Rewards URL.
RESEARCH = {
    "tjr": {
        "content_rewards_id": "33c3d5a9-84a9-40c8-b6e4-9904e4816339",
        "youtube_query": "TJR trades",
        "language": "en",
        "notes": "Clips of TJR (day trader/streamer) from his Kick streams.",
    },
    "tokyo_girl": {
        "content_rewards_id": "40046522-56d9-45ad-9198-faea8eca90c6",
        "youtube_query": "GTA 6 edit",
        "language": "en",
        "transcribe": False,   # music-only edits, nothing spoken to transcribe
        "rules": ("Silent 12-second GTA 6 edits (3 shots x 4s) with on-screen text only; the "
                  "song Tokyo Girl is added in TikTok. No talking/voiceover/dialogue. Themes: GTA 6 "
                  "news/rumors, memes & hype, Jason & Lucia couple memes, edits & Vice City views. "
                  "Caption must credit the song. Original edits only."),
        "notes": "Our editor controls: the 3 text beats, which visual each beat uses, text case/size, caption + hashtags.",
    },
    "clipup": {
        "content_rewards_id": "802cf95a-ea84-4070-9a96-8a917831cb16",
        "youtube_query": "GTA 6 gameplay funny moments",
        "language": "en",
        "notes": "GTA 6 streamer gameplay clips (Kick) with the ClipUp logo overlaid for the whole clip.",
    },
    "bichou": {
        "content_rewards_id": "ceff4682-947e-40c9-b7df-81a806c89943",
        "youtube_query": "bichou",
        "language": "fr",
        "notes": "French streamer clips (campaign paused).",
    },
}


# ---------------- Campaigns added by the scout (scout.py) ----------------
# Activated campaigns live in state/clips_state.json -> "active_campaigns", so
# the agent can add/retire them without anyone editing this file.

DYNAMIC_DEFAULTS = {
    "enabled": True,
    "clips_per_day": 1,
    "min_clip": 20.0,
    "max_clip": 55.0,
    "needs_approval": False,
    "no_currency_symbols": False,
    "skip_title": r"casino|slot|gambl|roobet|stake\b",
    "prefer_title": r"",
    "title_suffix": " #Shorts",
    "tags": [],
    "language": "en",
}


def all_campaigns(state: dict) -> dict:
    """Built-in campaigns above + scout-activated ones, with retired ones switched off."""
    out = {k: dict(v) for k, v in CAMPAIGNS.items()}
    for k, v in (state.get("active_campaigns") or {}).items():
        out[k] = {**DYNAMIC_DEFAULTS, **v}
    for k in state.get("retired", []):
        if k in out:
            out[k]["enabled"] = False
    return out


def research_targets(state: dict) -> dict:
    targets = {k: dict(v) for k, v in RESEARCH.items()}
    for k, v in (state.get("active_campaigns") or {}).items():
        targets.setdefault(k, {
            "content_rewards_id": v["content_rewards_id"],
            "youtube_query": v.get("youtube_query") or v["name"],
            "language": v.get("language", "en"),
            "notes": v.get("notes", ""),
        })
    return targets
