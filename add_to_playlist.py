import os
from typing import Any

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

TEST_VIDEO_ID = "m3q8CjvK0i0"  # long Quran recitation (safe public video)


def load_youtube() -> Any:
    if not os.path.exists("token.json"):
        raise RuntimeError("token.json not found")

    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return build("youtube", "v3", credentials=creds)


def main() -> None:
    playlist_id = os.getenv("PLAYLIST_ID")
    if not playlist_id:
        raise RuntimeError("PLAYLIST_ID not set")

    youtube = load_youtube()

    request = youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": TEST_VIDEO_ID,
                },
            }
        },
    )

    request.execute()
    print("✅ Test video added successfully")


if __name__ == "__main__":
    main()
