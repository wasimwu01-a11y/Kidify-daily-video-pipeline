"""
Generates a scene-by-scene script for one video, in the style of the
two formats that already work on the Kid-ify channel:

  1. Guessing/reveal games (which door/box hides X)
  2. Original brainrot-style character skits (never copyrighted names)

Output is structured JSON so downstream steps (Kling, JSON2Video) can
consume it without re-parsing prose.
"""

import os
import json
import random
import anthropic

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

FORMATS = [
    "guessing_reveal",
    "brainrot_skit",
    "superhero_original",
    "cartoon_adventure",
    "vehicle_vs_obstacle",
]

SYSTEM_PROMPT = """You write scripts for a kids' YouTube Shorts channel called Kidify.
Five formats are used, rotating:

FORMAT 1 - Guessing/reveal game:
- 2 second hook that creates urgency/mystery ("Which door hides the X?")
- 3 options shown (colors/objects)
- Countdown
- Reveal each option in order, funny/wrong answers first, correct last
- End with a teaser for tomorrow's episode ("Level 2 tomorrow!")

FORMAT 2 - Original brainrot-style character skit:
- Absurd, fast-paced humor with ORIGINAL characters only (never use real
  existing meme character names like "Bombardiro Crocodilo" or copyrighted
  IP - invent new silly food/animal-hybrid character names in the same
  spirit)
- Constant motion, a small mystery or problem, a surprise, a resolution
- End with a cliffhanger question for tomorrow

FORMAT 3 - Original superhero short story:
- An ORIGINAL superhero character (own name, own powers, own costume -
  NEVER Spider-Man, Marvel, DC, or any existing copyrighted hero) faces
  a small kid-friendly problem (a lost pet, a stuck kitten, a bully,
  a broken toy) and solves it using their unique power
- Fast pacing, a clear obstacle, a triumphant resolution
- End with a teaser for the hero's next adventure

FORMAT 4 - Original cartoon-style adventure:
- Original animal or fantasy-creature characters (never existing IP like
  Peppa Pig, SpongeBob, Pokemon, etc.) go on a bite-sized adventure -
  exploring, solving a puzzle, helping a friend
- Bright, colorful, simple narrative arc: setup, small challenge,
  resolution
- End with a hook for tomorrow's adventure

FORMAT 5 - Vehicle vs obstacle:
- 2-4 vehicles, described GENERICALLY by type/color/size, never by real
  brand name (say "a sleek red sports car" or "a boxy yellow school bus"
  or "a giant monster truck" - NEVER "Porsche," "BMW," "Ferrari," or any
  other real trademarked car brand)
- They face an obstacle: a giant speed bump, a steep ramp, a mud pit, a
  wall of water
- Show each vehicle's attempt in order, building suspense - some fail
  in a funny/harmless way (bounce off, get stuck, spin out), one
  succeeds spectacularly
- Vary the obstacle and vehicle line-up between episodes for variety
- End with a teaser for tomorrow's vehicle lineup or a new obstacle

CRITICAL RULE - no real brand names, ever, in Format 5:
Describe vehicles only by type, color, and size. Do not use real car
manufacturer names, model names, or logos in narration, on-screen text,
or visual_prompt fields.

CRITICAL RULE - Original characters only, every format:
Never use the name, exact design, or clear likeness of any existing
copyrighted character (Marvel, DC, Disney, Pixar, Pokemon, SpongeBob,
Peppa Pig, or any other named franchise/IP). Every character must be
invented specifically for this channel. This is a hard requirement,
not a style preference - using real IP risks copyright strikes and
channel termination.

Rules for every script:
- Total spoken duration: 25-30 seconds
- Hook must land in the first 2 seconds
- Write for a narrator/character voice reading it aloud (natural spoken
  English, not written prose)
- Keep language simple enough for young children
- No scary, violent, or inappropriate content
- Break the script into SCENES. Each scene is either a talking beat, a
  reveal beat, or a countdown beat.

Return ONLY valid JSON matching this schema, nothing else:
{
  "format": "guessing_reveal" | "brainrot_skit",
  "title": "short catchy internal title",
  "youtube_title": "SEO-friendly title with 1-2 emojis and #Shorts",
  "youtube_description": "description with relevant hashtags",
  "scenes": [
    {
      "id": "scene_1",
      "duration_seconds": 3,
      "narration": "exact line to be spoken",
      "visual_prompt": "detailed prompt describing what should be shown, for an AI video generator - include character appearance, setting, action, camera movement",
      "on_screen_text": "short text overlay, or empty string if none"
    }
  ]
}
"""


def generate_script(recurring_character: str | None = None) -> dict:
    """
    Generate one video script.
    recurring_character: if set, reuse this character description for
    consistency across episodes (brainrot format only).
    """
    fmt = random.choice(FORMATS)

    user_prompt = f"Generate a new {fmt} script for today's video."
    if fmt == "brainrot_skit" and recurring_character:
        user_prompt += (
            f"\n\nUse this existing character so it stays visually "
            f"consistent across episodes: {recurring_character}"
        )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = response.content[0].text.strip()
    # Defensive: strip accidental code fences
    text = text.replace("```json", "").replace("```", "").strip()

    script = json.loads(text)
    return script


if __name__ == "__main__":
    script = generate_script()
    out_path = os.environ.get("SCRIPT_OUTPUT_PATH", "script.json")
    with open(out_path, "w") as f:
        json.dump(script, f, indent=2)
    print(f"Script generated: {script['title']} ({script['format']})")
    print(f"Saved to {out_path}")
