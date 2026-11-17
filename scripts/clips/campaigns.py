"""
One entry per Kick-based clipping campaign. kick_clipper.py reads these.
To add a campaign: copy a block, change the Kick channel, rules and hashtags,
and add a step for it in .github/workflows/daily-clips.yml.
"""

CAMPAIGNS = {
    # ---------------- Bichou (ZK CLIPPING) ----------------
    "bichou": {
        "name": "Bichou",
        "enabled": False,            # PAUSED: campaign ended. Set True to resume.
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

    # ---------------- TJR (Reach) ----------------
    "tjr": {
        "name": "TJR",
        "enabled": True,
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
