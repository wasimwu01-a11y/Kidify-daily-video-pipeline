"""
Takes the visuals manifest (either AI-generated video clips or free
stock images with pan/zoom, depending on the video's format) plus
narration text, and assembles the final vertical short using
JSON2Video: adds voiceover (TTS), burned-in captions, and stitches
everything together in order.
"""

import os
import json
import time
import requests

JSON2VIDEO_API_KEY = os.environ["JSON2VIDEO_API_KEY"]
BASE_URL = "https://api.json2video.com/v2"

HEADERS = {
    "x-api-key": JSON2VIDEO_API_KEY,
    "Content-Type": "application/json",
}

POLL_INTERVAL_SECONDS = 10
MAX_POLL_ATTEMPTS = 60


def build_movie_json(manifest: list[dict], script: dict) -> dict:
    scenes = []
    for scene in manifest:
        # Backward compatibility: manifests saved before the hybrid
        # image/video system used "clip_url" and had no "media_type"
        # (they were always video). Support both old and new formats.
        media_url = scene.get("media_url") or scene.get("clip_url")
        media_type = scene.get("media_type", "video")

        if media_type == "image":
            visual_element = {
                "type": "image",
                "src": media_url,
                "resize": "cover",
                # Ken Burns style pan/zoom so a still photo doesn't
                # feel static - JSON2Video zooms in slowly over the
                # scene's duration.
                "zoom": 3,
            }
        else:
            visual_element = {
                "type": "video",
                "src": media_url,
                "resize": "cover",
            }

        scenes.append({
            "duration": scene["duration_seconds"],
            "elements": [
                visual_element,
                {
                    "type": "voice",
                    "text": scene["narration"],
                    "voice": "en-US-EmmaMultilingualNeural",
                },
                *([{
                    "type": "text",
                    "text": scene["on_screen_text"],
                    "style": "007",
                    "position": "top-center",
                    "settings": {"font-size": 60, "font-weight": "bold"},
                }] if scene["on_screen_text"] else []),
                {
                    "type": "subtitles",
                    "settings": {"font-size": 48, "position": "bottom-center"},
                },
            ],
        })

    return {
        "resolution": "custom",
        "width": 1080,
        "height": 1920,
        "quality": "high",
        "scenes": scenes,
        # No background music for now - JSON2Video needs a real,
        # publicly-hosted MP3 URL (it has no built-in music library).
        # To add music later: host a royalty-free track somewhere
        # public (e.g. commit an mp3 into this repo and reference it
        # via its raw.githubusercontent.com URL), then add an "audio"
        # element here pointing to that URL.
    }


def render(movie_json: dict) -> str:
    resp = requests.post(
        f"{BASE_URL}/movies",
        headers=HEADERS,
        json=movie_json,
        timeout=30,
    )
    resp.raise_for_status()
    project_id = resp.json()["project"]
    return project_id


def poll_for_render(project_id: str) -> str:
    for attempt in range(MAX_POLL_ATTEMPTS):
        resp = requests.get(
            f"{BASE_URL}/movies",
            headers=HEADERS,
            params={"project": project_id},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("movie", {}).get("status") == "done":
            return data["movie"]["url"]
        if data.get("movie", {}).get("status") == "error":
            raise RuntimeError(f"JSON2Video render failed: {data}")

        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError(f"JSON2Video render {project_id} did not finish in time")


def download_final_video(url: str, out_path: str):
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(resp.content)


if __name__ == "__main__":
    script_path = os.environ.get("SCRIPT_OUTPUT_PATH", "script.json")
    manifest_path = os.environ.get("MANIFEST_OUTPUT_PATH", "clip_manifest.json")
    final_video_path = os.environ.get("FINAL_VIDEO_PATH", "final_video.mp4")

    with open(script_path) as f:
        script = json.load(f)
    with open(manifest_path) as f:
        manifest = json.load(f)

    movie_json = build_movie_json(manifest, script)
    project_id = render(movie_json)
    print(f"Render started: {project_id}")

    video_url = poll_for_render(project_id)
    download_final_video(video_url, final_video_path)

    print(f"Final video saved to {final_video_path}")
