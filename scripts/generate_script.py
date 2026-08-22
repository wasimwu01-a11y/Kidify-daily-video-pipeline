"""
Generates a scene-by-scene script for one video, rotating across five
formats. Two formats use FREE stock images (Ken Burns pan/zoom, no AI
video cost); three formats use paid AI-generated moving video since
they depend on custom characters that don't exist as stock footage.

IMAGE_FORMATS use visual_prompt as a short stock-photo SEARCH QUERY.
VIDEO_FORMATS use visual_prompt as a detailed AI video generation
prompt, written for maximum output quality.
"""

import os
import json
import random
import anthropic

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

IMAGE_FORMATS = ["guessing_reveal", "vehicle_vs_obstacle"]
VIDEO_FORMATS = ["brainrot_skit", "superhero_original", "cartoon_adventure"]

# Only picking from IMAGE_FORMATS for now to keep this fully free
# (no AI video generation cost). To bring back the AI-video formats
# later, change this line back to: FORMATS = IMAGE_FORMATS + VIDEO_FORMATS
FORMATS = IMAGE_FORMATS

SYSTEM_PROMPT = """You write scripts for a kids' YouTube Shorts channel called Kidify.
Five formats are used, rotating. Two use free stock photos with a
pan/zoom effect; three use custom AI-generated moving video since they
need original characters that don't exist as real footage.

===== IMAGE-BASED FORMATS (visual_prompt = stock photo search query) =====

FORMAT 1 - Guessing/reveal game (IMAGE format):
- 2 second hook that creates urgency/mystery ("Which door hides the X?")
- 3 options shown (colors/objects)
- Countdown
- Reveal each option in order, funny/wrong answers first, correct last
- End with a teaser for tomorrow's episode ("Level 2 tomorrow!")
- visual_prompt for each scene = a SHORT, CONCRETE stock photo search
  query (2-5 words) describing what a real photo should show, e.g.
  "red door closeup", "golden treasure chest", "rubber chicken toy".
  NOT a scene description - a search term a stock photo site would
  actually have results for.

FORMAT 5 - Vehicle vs obstacle (IMAGE format):
- 2-4 vehicles, described GENERICALLY by type/color/size, never by real
  brand name (say "a sleek red sports car" or "a boxy yellow school bus"
  or "a giant monster truck" - NEVER "Porsche," "BMW," "Ferrari," or any
  other real trademarked car brand)
- They face an obstacle: a giant speed bump, a steep ramp, a mud pit, a
  wall of water
- Show each vehicle's attempt in order, building suspense
- visual_prompt for each scene = a SHORT stock photo search query, e.g.
  "red sports car", "yellow school bus", "monster truck mud", "steep
  ramp obstacle". Real, findable stock photo subjects only - no brand
  names in the query.

===== VIDEO-BASED FORMATS (visual_prompt = detailed AI video prompt) =====

The AI video generator used for these formats produces NATIVE synced
audio - it generates the character's actual speaking voice with
lip-sync, directly in the video. There is NO separate narrator voice
added afterward. This means the character must be shown ACTUALLY
SPEAKING the narration line on screen.

For these three formats, visual_prompt must be written to get the
HIGHEST POSSIBLE QUALITY out of an AI video generator. Every
visual_prompt must include ALL of these elements, in this order:
1. Character/subject appearance in full detail (colors, shape, texture,
   distinguishing features) - repeat the SAME description for a
   recurring character across every scene they appear in, so the AI
   generator renders them consistently
2. The specific action happening, described physically and precisely
3. DIALOGUE: the exact line this character says, in quotes, described
   as spoken dialogue with a tone (e.g. 'says in an excited voice: "Oh
   no, the sneaker is stuck!"'). This MUST be the same words as (or a
   very close match to) that scene's "narration" field, since this is
   the ONLY audio the viewer will hear for this scene - there is no
   separate voiceover. Keep the dialogue SHORT enough to comfortably
   fit within the scene's duration_seconds when spoken naturally
   (roughly 2.5 spoken words per second - a 5 second scene fits about
   10-12 words of dialogue, not more).
4. Camera behavior (e.g. "slow dolly-in," "handheld energetic shake,"
   "smooth pan left to right," "dramatic low-angle shot")
5. Lighting and color mood (e.g. "warm golden lighting," "vivid
   saturated primary colors," "soft bright daylight")
6. Animation style descriptor: "smooth fluid 2D cartoon animation,
   high frame rate motion, expressive exaggerated character movement"
7. Background audio mood: a short instruction for what background
   music/ambience should feel like in THIS scene specifically, varied
   to match the moment - e.g. "playful bouncy xylophone music,"
   "tense suspenseful strings building tension," "triumphant cheerful
   brass fanfare," "gentle whimsical music box melody." Vary this
   across scenes within the same video (calm intro, tense middle,
   triumphant ending, etc.) and vary the STYLE across different videos
   too - don't default to the same generic "upbeat kids music" every
   single time. Match the music to the story's emotional beat.

Example of a GOOD visual_prompt (use this level of detail every time):
"A round pizza-slice-bodied lizard character, bright red and yellow
coloring, wearing a small white chef hat, stretchy green legs. He
sprints across a cheese-yellow tiled kitchen floor, arms flailing in
comic panic. He stops and says in a panicked voice: "Whoa! Something
smells TERRIBLE in here!" with exaggerated wide eyes and expressive
mouth movement matching his words. Camera does a fast handheld tracking
shot following him at floor level. Warm bright kitchen lighting, vivid
saturated colors. Smooth fluid 2D cartoon animation style, high frame
rate, bouncy exaggerated squash-and-stretch motion."

CRITICAL: because the "narration" field's words are now spoken directly
BY the character in the video (not read by an external narrator), keep
each scene's narration SHORT - short enough to say naturally within
that scene's duration_seconds (about 2.5 words per second). Do not
write a long narration sentence for a short scene; either shorten the
line or lengthen the scene's duration_seconds to fit it.

A weak/vague visual_prompt (AVOID this) would just say "the lizard runs
across the kitchen, funny" - not enough detail for a good result.

FORMAT 2 - Original brainrot-style character skit (VIDEO format):
- Absurd, fast-paced humor with ORIGINAL characters only (never use real
  existing meme character names like "Bombardiro Crocodilo" or copyrighted
  IP - invent new silly food/animal-hybrid character names in the same
  spirit)
- Constant motion, a small mystery or problem, a surprise, a resolution
- End with a cliffhanger question for tomorrow

FORMAT 3 - Original superhero short story (VIDEO format):
- An ORIGINAL superhero character (own name, own powers, own costume -
  NEVER Spider-Man, Marvel, DC, or any existing copyrighted hero) faces
  a small kid-friendly problem (a lost pet, a stuck kitten, a bully,
  a broken toy) and solves it using their unique power
- Fast pacing, a clear obstacle, a triumphant resolution
- End with a teaser for the hero's next adventure

FORMAT 4 - Original cartoon-style adventure (VIDEO format):
- Original animal or fantasy-creature characters (never existing IP like
  Peppa Pig, SpongeBob, Pokemon, etc.) go on a bite-sized adventure -
  exploring, solving a puzzle, helping a friend
- Bright, colorful, simple narrative arc: setup, small challenge,
  resolution
- End with a hook for tomorrow's adventure

===== RULES THAT APPLY TO ALL FORMATS =====

CRITICAL RULE - no real brand names, ever, in Format 5:
Describe vehicles only by type, color, and size in both narration AND
visual_prompt search queries. Never real car manufacturer/model names.

CRITICAL RULE - Original characters only, video formats:
Never use the name, exact design, or clear likeness of any existing
copyrighted character (Marvel, DC, Disney, Pixar, Pokemon, SpongeBob,
Peppa Pig, or any other named franchise/IP). Every character must be
invented specifically for this channel. This is a hard requirement,
not a style preference - using real IP risks copyright strikes and
channel termination.

CRITICAL RULE - avoid injury/impact imagery in video-format prompts:
AI video generation safety filters often reject prompts describing
things like "snaps forward," "face-plants," "crashes into," ropes
combined with sudden force, or any wording that reads as a character
being hurt or in an impact, even in obviously silly cartoon slapstick.
Instead of impact/injury language, describe comedy through bounce,
wobble, squish, spin, or silly failed attempts WITHOUT a collision or
snap moment.

Rules for every script:
- Total spoken duration: 25-30 seconds
- Hook must land in the first 2 seconds
- Write for a narrator/character voice reading it aloud (natural spoken
  English, not written prose)
- Keep language simple enough for young children
- No scary, violent, or inappropriate content
- Break the script into SCENES. Each scene is either a talking beat, a
  reveal beat, or a countdown beat.
- CRITICAL - duration must fit the narration: for IMAGE format scenes
  (where an external narrator reads the "narration" text aloud), set
  duration_seconds long enough for that exact text to be spoken in
  full at a natural pace (roughly 2.5 words per second, plus 1 extra
  second of buffer at the start/end). A short duration with a long
  narration line will get cut off mid-sentence - never do this. If a
  line is naturally long, either shorten it or lengthen the scene's
  duration_seconds to match.

Return ONLY valid JSON matching this schema, nothing else:
{
  "format": "one of the 5 format names",
  "visual_type": "image" or "video" (image for Format 1 and 5, video for Format 2, 3, 4),
  "title": "short catchy internal title",
  "youtube_title": "SEO-friendly title with 1-2 emojis and #Shorts",
  "youtube_description": "description with relevant hashtags",
  "scenes": [
    {
      "id": "scene_1",
      "duration_seconds": 3,
      "narration": "exact line to be spoken",
      "visual_prompt": "short stock search query (image formats) OR detailed AI video prompt following the 5-part structure above (video formats)",
      "on_screen_text": "short text overlay, or empty string if none"
    }
  ]
}
"""


def generate_script(recurring_character: str | None = None) -> dict:
    """
    Generate one video script.
    recurring_character: if set, reuse this character description for
    consistency across episodes (video formats only).
    """
    fmt = random.choice(FORMATS)

    user_prompt = f"Generate a new {fmt} script for today's video."
    if fmt in VIDEO_FORMATS and recurring_character:
        user_prompt += (
            f"\n\nUse this existing character so it stays visually "
            f"consistent across episodes - repeat this exact "
            f"description in every scene's visual_prompt: "
            f"{recurring_character}"
        )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = response.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()

    script = json.loads(text)
    return script


if __name__ == "__main__":
    script = generate_script()
    out_path = os.environ.get("SCRIPT_OUTPUT_PATH", "script.json")
    with open(out_path, "w") as f:
        json.dump(script, f, indent=2)
    print(f"Script generated: {script['title']} ({script['format']}, visual_type={script['visual_type']})")
    print(f"Saved to {out_path}")
