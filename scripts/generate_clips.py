"""
Sends each scene's visual_prompt to Wan 2.6 (via fal.ai) and gets back
a moving video clip URL per scene.

RESUME SUPPORT: if clip_manifest.json already exists (loaded from a
previous run's checkpoint), scenes already present in it are SKIPPED -
only missing scenes are generated. This means a run that dies partway
through (insufficient credits, network issue, etc.) never wastes the
clips it already paid for.

Progress is saved to disk after EVERY successful clip, not just at the
end - so even a hard crash mid-run leaves recoverable progress on disk
for the workflow to checkpoint.
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
    for attempt in range(MAX_POLL_ATTEMPTS):
        resp = requests.get(urls["status_url"], headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")

        if status == "COMPLETED":
            result_resp = requests.get(urls["response_url"], headers=HEADERS, timeout=30)
            if result_resp.status_code == 422:
                raise RuntimeError(
                    f"fal.ai rejected this clip at the result stage (422). "
                    f"This usually means the prompt was flagged by content "
                    f"moderation. Response: {result_resp.text}"
                )
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


def load_existing_manifest(manifest_path: str) -> list[dict]:
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            existing = json.load(f)
        if existing:
            print(f"Resuming: found {len(existing)} already-generated clip(s) in {manifest_path}")
        return existing
    return []


def save_manifest(manifest: list[dict], manifest_path: str):
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)


def generate_scene_with_retry(scene: dict):
    try:
        urls = start_generation(scene)
        return poll_for_result(urls)
    except RuntimeError as e:
        if "content moderation" in str(e).lower() or "422" in str(e):
            print(f"  Scene flagged, retrying with softened prompt: {e}")
            softened_scene = dict(scene)
            softened_scene["visual_prompt"] = (
                scene["visual_prompt"]
                .replace("crash", "bump")
                .replace("snap", "wobble")
                .replace("face-plant", "plop down")
                .replace("collide", "bounce off")
            )
            urls = start_generation(softened_scene)
            return poll_for_result(urls)
        raise


def generate_all_clips(script: dict, manifest_path: str) -> list[dict]:
    clip_manifest = load_existing_manifest(manifest_path)
    already_done_ids = {c["scene_id"] for c in clip_manifest}

    for scene in script["scenes"]:
        if scene["id"] in already_done_ids:
            print(f"Skipping {scene['id']} - already generated in a previous run.")
            continue

        print(f"Generating clip for {scene['id']}...")
        try:
            video_url = generate_scene_with_retry(scene)
        except InsufficientCreditsError as e:
            # Save whatever we have so far before failing - this is
            # what makes the resume system actually work.
            save_manifest(clip_manifest, manifest_path)
            print(f"::error::{e}")
            sys.exit(1)
        except Exception as e:
            save_manifest(clip_manifest, manifest_path)
            print(f"::error::Scene {scene['id']} failed: {e}")
            sys.exit(1)

        clip_manifest.append({
            "scene_id": scene["id"],
            "clip_url": video_url,
            "narration": scene["narration"],
            "on_screen_text": scene["on_screen_text"],
            "duration_seconds": scene["duration_seconds"],
        })
        # Save after EVERY clip, not just at the end - protects
        # progress even if the process dies unexpectedly.
        save_manifest(clip_manifest, manifest_path)
        print(f"  -> clip ready: {video_url}")

    return clip_manifest


if __name__ == "__main__":
    script_path = os.environ.get("SCRIPT_OUTPUT_PATH", "script.json")
    manifest_path = os.environ.get("MANIFEST_OUTPUT_PATH", "clip_manifest.json")

    with open(script_path) as f:
        script = json.load(f)

    manifest = generate_all_clips(script, manifest_path)

    print(f"All clips generated. Manifest saved to {manifest_path}")
