"""
Generates the visual for every scene in the script. Branches based on
script["visual_type"]:

  "video" -> Wan 2.6 via fal.ai (paid, for custom character formats)
  "image" -> Pexels stock photo search (FREE, for guessing/vehicle formats)

RESUME SUPPORT: scenes already present in an existing clip_manifest.json
are skipped, and progress is saved after every single scene - so a run
that dies partway through never wastes what it already generated/paid for.
"""

import os
import sys
import json
import time
import requests

FAL_API_KEY = os.environ.get("FAL_API_KEY", "")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

FAL_BASE_URL = "https://queue.fal.run"
MODEL_ID = "wan/v2.6/text-to-video"
FAL_HEADERS = {
    "Authorization": f"Key {FAL_API_KEY}",
    "Content-Type": "application/json",
}

PEXELS_HEADERS = {"Authorization": PEXELS_API_KEY}

POLL_INTERVAL_SECONDS = 8
MAX_POLL_ATTEMPTS = 60


class InsufficientCreditsError(Exception):
    pass


# ===== VIDEO GENERATION (Wan 2.6 via fal.ai) =====

def start_generation(scene: dict, max_retries: int = 3) -> dict:
    duration = "5" if scene["duration_seconds"] <= 7 else "10"
    payload = {
        "prompt": scene["visual_prompt"],
        "aspect_ratio": "9:16",
        "duration": duration,
    }

    for attempt in range(max_retries):
        resp = requests.post(f"{FAL_BASE_URL}/{MODEL_ID}", headers=FAL_HEADERS, json=payload, timeout=30)

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
        return {"status_url": data["status_url"], "response_url": data["response_url"]}

    raise RuntimeError(f"fal.ai still rate-limited after {max_retries} retries.")


def poll_for_video_result(urls: dict) -> str:
    for attempt in range(MAX_POLL_ATTEMPTS):
        resp = requests.get(urls["status_url"], headers=FAL_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")

        if status == "COMPLETED":
            result_resp = requests.get(urls["response_url"], headers=FAL_HEADERS, timeout=30)
            if result_resp.status_code == 422:
                raise RuntimeError(
                    f"fal.ai rejected this clip at the result stage (422). "
                    f"Likely flagged by content moderation. Response: {result_resp.text}"
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


def generate_video_for_scene(scene: dict) -> str:
    try:
        urls = start_generation(scene)
        return poll_for_video_result(urls)
    except RuntimeError as e:
        if "content moderation" in str(e).lower() or "422" in str(e):
            print(f"  Scene flagged, retrying with softened prompt: {e}")
            softened = dict(scene)
            softened["visual_prompt"] = (
                scene["visual_prompt"]
                .replace("crash", "bump")
                .replace("snap", "wobble")
                .replace("face-plant", "plop down")
                .replace("collide", "bounce off")
            )
            urls = start_generation(softened)
            return poll_for_video_result(urls)
        raise


# ===== IMAGE SEARCH (Pexels, free) =====

def get_image_for_scene(scene: dict) -> str:
    if not PEXELS_API_KEY:
        raise RuntimeError(
            "PEXELS_API_KEY is not set. Add it as a GitHub secret - "
            "sign up free at pexels.com/api to get one."
        )

    query = scene["visual_prompt"]
    resp = requests.get(
        "https://api.pexels.com/v1/search",
        headers=PEXELS_HEADERS,
        params={"query": query, "per_page": 5, "orientation": "portrait"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    photos = data.get("photos", [])
    if not photos:
        # Fallback: broaden the search if the specific query had no results
        broader_query = query.split()[0] if query.split() else query
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers=PEXELS_HEADERS,
            params={"query": broader_query, "per_page": 5},
            timeout=30,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])

    if not photos:
        raise RuntimeError(f"Pexels found no images for query: '{query}'")

    return photos[0]["src"]["large2x"]


# ===== SHARED RESUME / MANIFEST LOGIC =====

def load_existing_manifest(manifest_path: str) -> list[dict]:
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            existing = json.load(f)
        if existing:
            print(f"Resuming: found {len(existing)} already-generated visual(s) in {manifest_path}")
        return existing
    return []


def save_manifest(manifest: list[dict], manifest_path: str):
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)


def generate_all_visuals(script: dict, manifest_path: str) -> list[dict]:
    visual_type = script.get("visual_type", "video")
    clip_manifest = load_existing_manifest(manifest_path)
    already_done_ids = {c["scene_id"] for c in clip_manifest}

    print(f"Visual type for this video: {visual_type}")

    for scene in script["scenes"]:
        if scene["id"] in already_done_ids:
            print(f"Skipping {scene['id']} - already generated in a previous run.")
            continue

        print(f"Generating {visual_type} for {scene['id']}...")
        try:
            if visual_type == "image":
                media_url = get_image_for_scene(scene)
            else:
                media_url = generate_video_for_scene(scene)
        except InsufficientCreditsError as e:
            save_manifest(clip_manifest, manifest_path)
            print(f"::error::{e}")
            sys.exit(1)
        except Exception as e:
            save_manifest(clip_manifest, manifest_path)
            print(f"::error::Scene {scene['id']} failed: {e}")
            sys.exit(1)

        clip_manifest.append({
            "scene_id": scene["id"],
            "media_type": visual_type,
            "media_url": media_url,
            "narration": scene["narration"],
            "on_screen_text": scene["on_screen_text"],
            "duration_seconds": scene["duration_seconds"],
        })
        save_manifest(clip_manifest, manifest_path)
        print(f"  -> ready: {media_url}")

    return clip_manifest


if __name__ == "__main__":
    script_path = os.environ.get("SCRIPT_OUTPUT_PATH", "script.json")
    manifest_path = os.environ.get("MANIFEST_OUTPUT_PATH", "clip_manifest.json")

    with open(script_path) as f:
        script = json.load(f)

    manifest = generate_all_visuals(script, manifest_path)

    print(f"All visuals generated. Manifest saved to {manifest_path}")
