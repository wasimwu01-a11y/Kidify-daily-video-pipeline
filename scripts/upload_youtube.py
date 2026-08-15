"""
Uploads the final rendered video to the Kid-ify YouTube channel only.
No TikTok cross-posting in this pipeline (unlike the old one).
"""

import os
import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

CLIENT_ID = os.environ["YOUTUBE_CLIENT_ID"]
CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]


def get_authenticated_service():
    creds = Credentials(
        token=None,
        refresh_token=REFRESH_TOKEN,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    return build("youtube", "v3", credentials=creds)


def upload_short(video_path: str, title: str, description: str):
    youtube = get_authenticated_service()

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "24",  # Entertainment
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": True,
            # Discloses that this video contains AI-generated/altered
            # content. YouTube's own guidance says this is specifically
            # required for REALISTIC synthetic media (content that
            # could be mistaken for real footage) - obviously stylized
            # cartoon content like this technically may not require it,
            # but setting it anyway is a safe, transparent default.
            "containsSyntheticMedia": True,
        },
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"Uploaded: https://www.youtube.com/shorts/{video_id}")
    return video_id


if __name__ == "__main__":
    script_path = os.environ.get("SCRIPT_OUTPUT_PATH", "script.json")
    final_video_path = os.environ.get("FINAL_VIDEO_PATH", "final_video.mp4")

    with open(script_path) as f:
        script = json.load(f)

    upload_short(
        video_path=final_video_path,
        title=script["youtube_title"],
        description=script["youtube_description"],
    )
