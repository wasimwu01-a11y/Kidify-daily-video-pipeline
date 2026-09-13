"""
Assembles the final vertical short using FFmpeg (free, open-source,
preinstalled on GitHub Actions runners) instead of JSON2Video (paid).

For each scene:
  - IMAGE scenes: downloads the photo, applies a slow zoom (Ken Burns)
    effect, generates narration via edge-tts (free, Microsoft neural
    voices, no API key needed), overlays on-screen text + a caption,
    and sets the clip's length to match however long the narration
    actually takes to speak (so nothing gets cut off).
  - VIDEO scenes: uses the AI-generated clip as-is (it already has its
    own native audio) - just re-encodes for consistent concatenation.

All scene clips are then concatenated into one final vertical video.

Trade-offs vs JSON2Video (disclosed, not hidden):
  - Emoji in on-screen text/captions are stripped (free text rendering
    doesn't support color emoji fonts without extra setup)
  - Captions are one static line per scene, not word-by-word highlighted
"""

import os
import re
import json
import subprocess
import tempfile
import requests
import asyncio
import edge_tts

VOICE = "en-US-EmmaMultilingualNeural"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def strip_emoji(text: str) -> str:
    emoji_pattern = re.compile(
        "["
        "\U0001F300-\U0001FAFF"
        "\U00002600-\U000027BF"
        "\U0001F1E6-\U0001F1FF"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()


def escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\u2019")
        .replace("%", "\\%")
    )


def download_file(url: str, out_path: str):
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(resp.content)


def generate_tts(text: str, out_path: str):
    async def _run():
        communicate = edge_tts.Communicate(text, VOICE)
        await communicate.save(out_path)
    asyncio.run(_run())


def get_audio_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def build_image_scene(scene: dict, work_dir: str, index: int) -> str:
    image_path = os.path.join(work_dir, f"scene_{index}.jpg")
    audio_path = os.path.join(work_dir, f"scene_{index}.mp3")
    output_path = os.path.join(work_dir, f"scene_{index}_final.mp4")

    media_url = scene.get("media_url") or scene.get("clip_url")
    download_file(media_url, image_path)
    generate_tts(scene["narration"], audio_path)

    audio_duration = get_audio_duration(audio_path)
    duration = max(scene.get("duration_seconds", 3), audio_duration + 0.5)

    fps = 30
    total_frames = int(duration * fps)
    zoom_filter = (
        f"scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,"
        f"zoompan=z='min(zoom+0.0008,1.15)':d={total_frames}:"
        f"s=1080x1920:fps={fps}"
    )

    drawtext_filters = []
    on_screen_text = strip_emoji(scene.get("on_screen_text", ""))
    if on_screen_text:
        escaped = escape_drawtext(on_screen_text)
        drawtext_filters.append(
            f"drawtext=fontfile={FONT_PATH}:text='{escaped}':"
            f"fontcolor=white:fontsize=64:borderw=4:bordercolor=black:"
            f"x=(w-text_w)/2:y=120"
        )

    caption_text = strip_emoji(scene["narration"])
    escaped_caption = escape_drawtext(caption_text)
    drawtext_filters.append(
        f"drawtext=fontfile={FONT_PATH}:text='{escaped_caption}':"
        f"fontcolor=white:fontsize=44:borderw=3:bordercolor=black:"
        f"x=(w-text_w)/2:y=h-200:line_spacing=8"
    )

    full_filter = zoom_filter + "," + ",".join(drawtext_filters)

    subprocess.run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-filter_complex", f"[0:v]{full_filter}[v]",
        "-map", "[v]", "-map", "1:a",
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ], check=True, capture_output=True)

    return output_path


def build_video_scene(scene: dict, work_dir: str, index: int) -> str:
    input_path = os.path.join(work_dir, f"scene_{index}_raw.mp4")
    output_path = os.path.join(work_dir, f"scene_{index}_final.mp4")

    media_url = scene.get("media_url") or scene.get("clip_url")
    download_file(media_url, input_path)

    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        output_path,
    ], check=True, capture_output=True)

    return output_path


def concatenate_clips(clip_paths: list[str], output_path: str, work_dir: str):
    concat_list_path = os.path.join(work_dir, "concat_list.txt")
    with open(concat_list_path, "w") as f:
        for path in clip_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list_path,
        "-c", "copy",
        output_path,
    ], check=True, capture_output=True)


def assemble(manifest: list[dict], script: dict, final_video_path: str):
    with tempfile.TemporaryDirectory() as work_dir:
        clip_paths = []
        for i, scene in enumerate(manifest):
            media_type = scene.get("media_type", "video")
            print(f"Rendering {scene['scene_id']} ({media_type})...")
            if media_type == "image":
                clip_path = build_image_scene(scene, work_dir, i)
            else:
                clip_path = build_video_scene(scene, work_dir, i)
            clip_paths.append(clip_path)

        print("Concatenating all scenes...")
        concatenate_clips(clip_paths, final_video_path, work_dir)


if __name__ == "__main__":
    script_path = os.environ.get("SCRIPT_OUTPUT_PATH", "script.json")
    manifest_path = os.environ.get("MANIFEST_OUTPUT_PATH", "clip_manifest.json")
    final_video_path = os.environ.get("FINAL_VIDEO_PATH", "final_video.mp4")

    with open(script_path) as f:
        script = json.load(f)
    with open(manifest_path) as f:
        manifest = json.load(f)

    assemble(manifest, script, final_video_path)

    print(f"Final video saved to {final_video_path}")
