"""
Sends each scene's visual_prompt to Kling AI and downloads the
resulting video clip. Runs after generate_script.py.

Handles the most common real-world failure explicitly: running out of
credits. When that happens, this script fails LOUDLY with a clear
message in the GitHub Actions log, rather than a vague timeout.
"""

import os
import sys
import json
import time
import requests

KLING_API_KEY = os.environ["KLING_API_KEY"]
KLING_BASE_URL = "https://api-singapore.klingai.com"  # international endpoint

HEADERS = {
    "Authorization": f"Bearer {KLING_API_KEY}",
    "Content-Type": "application/json",
}

POLL_INTERVAL_SECONDS = 10
MAX_POLL_ATTEMPTS = 60  # ~10 minutes per clip


class InsufficientCreditsError(Exception):
    pass


def start_generation(scene: dict) -> str:
    """Kick off a Kling generation job for one scene. Returns task_id."""
    payload = {
        "model_name": "kling-v2.6-pro",
        "prompt": scene["visual_prompt"],
        "duration": str(min(max(scene["duration_seconds"], 3), 10)),
        "aspect_ratio": "9:16",
    }

    resp = requests.post(
        f"{KLING_BASE_URL}/v1/videos/text2video",
        headers=HEADERS,
        json=payload,
        timeout=30,
    )

    if resp.status_code == 402 or "insufficient" in resp.text.lower():
        raise InsufficientCreditsError(
            "Kling API: insufficient balance. Top up credits at "
            "kling.ai before re-running this workflow."
        )

    resp.raise_for_status()
    data = resp.json()
    task_id = data.get("data", {}).get("task_id") or data.get("task_id")
    if not task_id:
        raise RuntimeError(f"Kling API did not return a task_id: {data}")
    return task_id


def poll_for_result(task_id: str) -> str:
    """Poll until the clip is ready. Returns the video download URL."""
    for attempt in range(MAX_POLL_ATTEMPTS):
        resp = requests.get(
            f"{KLING_BASE_URL}/v1/videos/text2video/{task_id}",
            headers=HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        status = data.get("task_status")

        if status == "succeed":
            videos = data.get("task_result", {}).get("videos", [])
            if not videos:
                raise RuntimeError(f"Kling task succeeded but no video URL: {data}")
            return videos[0]["url"]

        if status == "failed":
            raise RuntimeError(f"Kling generation failed: {data}")

        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError(f"Kling task {task_id} did not finish in time")


def generate_all_clips(script: dict, output_dir: str) -> list[dict]:
    """
    NOTE: we deliberately do NOT download clips to local disk here.
    JSON2Video's assembly step needs a publicly reachable URL for each
    clip's "src" field, and Kling's own result URL already is one
    (typically valid for a limited time window, which is fine since
    assembly runs immediately after in the same workflow run).
    """
    os.makedirs(output_dir, exist_ok=True)
    clip_manifest = []

    for scene in script["scenes"]:
        print(f"Generating clip for {scene['id']}...")
        try:
            task_id = start_generation(scene)
            video_url = poll_for_result(task_id)
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
