"""
Sends each scene's visual_prompt to Wan 2.6 (via fal.ai) and gets back
a moving video clip URL per scene. Runs after generate_script.py.

Switched from Kling to fal.ai/Wan 2.6 because:
- Kling's official platform currently has no self-serve top-up (only
  "contact sales"), which breaks unattended automation
- fal.ai has instant card-based billing
- Wan 2.6 is cheaper per-second than Kling and has explicit tooling
  for character consistency across shots (useful for recurring
  characters like brainrot-skit characters)

Handles insufficient-balance explicitly so failures are clear in the
GitHub Actions log rather than a vague timeout.
"""

import os
import sys
import json
import time
import requests

FAL_API_KEY = os.environ["FAL_API_KEY"]
FAL_BASE_URL = "https://queue.fal.run"
MODEL_ID = "wan/v2.6/text-to-video"

HEADERS = {
    "Authorization": f"Key {FAL_API_KEY}",
    "Content-Type": "application/json",
}

POLL_INTERVAL_SECONDS = 8
MAX_POLL_ATTEMPTS = 60  # ~8 minutes per clip


class InsufficientCreditsError(Exception):
    pass


def start_generation(scene: dict, max_retries: int = 3) -> dict:
    """Kick off a Wan 2.6 generation job for one scene.
    Returns dict with status_url and response_url."""
    # Wan 2.6 accepts 5 or 10 second durations
    duration = "5" if scene["duration_seconds"] <= 7 else "10"

    payload = {
        "prompt": scene["visual_prompt"],
        "aspect_ratio": "9:16",
        "duration": duration,
    }

    for attempt in range(max_retries):
        resp = requests.post(
            f"{FAL_BASE_URL}/{MODEL_ID}",
            headers=HEADERS,
            json=payload,
            timeout=30,
        )

        if resp.status_code == 429:
            wait_time = 20 * (attempt + 1)
            print(f"  Rate limited. Waiting {wait_time}s before retry.")
            time.sleep(wait_time)
            continue

        if resp.status_code in (402, 403) or "insufficient" in resp.text.lower() or "balance" in resp.text.lower():
            raise InsufficientCreditsError(
                "fal.ai: insufficient balance. Top up credits at "
                "fal.ai/dashboard/billing before re-running this workflow."
            )

        if resp.status_code == 400:
            raise RuntimeError(f"fal.ai rejected the request: {resp.text}")

        resp.raise_for_status()
        data = resp.json()
        return {
            "status_url": data["status_url"],
            "response_url": data["response_url"],
        }

    raise RuntimeError(f"fal.ai still rate-limited after {max_retries} retries.")


def poll_for_result(urls: dict) -> str:
    """Poll until the clip is ready. Returns the video download URL."""
    for attempt in range(MAX_POLL_ATTEMPTS):
        resp = requests.get(urls["status_url"], headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")

        if status == "COMPLETED":
            result_resp = requests.get(urls["response_url"], headers=HEADERS, timeout=30)
            result_resp.raise_for_status()
            result = result_resp.json()
            video_url = result.get("video", {}).get("url")
            if not video_url:
                raise RuntimeError(f"fal.ai completed but no video URL found: {result}")
            return video_url

        if status in ("ERROR", "FAILED"):
            raise RuntimeError(f"fal.ai generation failed: {data}")

        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError("fal.ai task did not finish in time")


def generate_all_clips(script: dict, output_dir: str) -> list[dict]:
    os.makedirs(output_dir, exist_ok=True)
    clip_manifest = []

    for scene in script["scenes"]:
        print(f"Generating clip for {scene['id']}...")
        try:
            urls = start_generation(scene)
            video_url = poll_for_result(urls)
        except InsufficientCreditsError as e:
            print(f"::error::{e}")
            sys.exit(1)

        clip_manifest.append({
            "scene_id": scene["id"],
            "clip_url": video_url,
            "narration": scene["narration"],
            "on_screen_text": scene["on_screen_text"],
            "duration_seconds": scene["duration_seconds"],
        })
        print(f"  -> clip ready: {video_url}")

    return clip_manifest


if __name__ == "__main__":
    script_path = os.environ.get("SCRIPT_OUTPUT_PATH", "script.json")
    output_dir = os.environ.get("CLIPS_OUTPUT_DIR", "clips")
    manifest_path = os.environ.get("MANIFEST_OUTPUT_PATH", "clip_manifest.json")

    with open(script_path) as f:
        script = json.load(f)

    manifest = generate_all_clips(script, output_dir)

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"All clips generated. Manifest saved to {manifest_path}")
