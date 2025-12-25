import os
from typing import Any

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

TEST_VIDEO_ID = "m3q8CjvK0i0"  # any long public Quran video id


def load_youtube() -> Any:
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def main() -> None:
    playlist_id = os.getenv("PLAYLIST_ID")
    if not playlist_id:
        raise RuntimeError("PLAYLIST_ID missing")

    yt = load_youtube()

    req = yt.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": TEST_VIDEO_ID},
            }
        },
    )
    req.execute()
    print("✅ Added test video")


if __name__ == "__main__":
    main()
