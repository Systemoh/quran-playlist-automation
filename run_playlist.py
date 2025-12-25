import os
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

TEST_VIDEO_ID = "m3q8CjvK0i0"  # change later if needed


def load_youtube() -> Any:
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def video_accessible(yt: Any, video_id: str) -> bool:
    resp = yt.videos().list(part="id,status", id=video_id, maxResults=1).execute()
    items = resp.get("items", [])
    if not items:
        return False
    status = items[0].get("status", {})
    if status.get("privacyStatus") == "private":
        return False
    return True


def main() -> None:
    playlist_id = os.getenv("PLAYLIST_ID")
    if not playlist_id:
        raise RuntimeError("PLAYLIST_ID missing")

    yt = load_youtube()

    # PROVE which channel the token belongs to
    me = yt.channels().list(part="snippet", mine=True).execute()
    print("Authenticated channel:", me["items"][0]["snippet"]["title"])

    # Validate video first (prevents hard-fail)
    if not video_accessible(yt, TEST_VIDEO_ID):
        print(f"⚠️ Skipping video (not found / not accessible): {TEST_VIDEO_ID}")
        return

    try:
        yt.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": TEST_VIDEO_ID},
                }
            },
        ).execute()
        print("✅ Added test video")
    except HttpError as e:
        print("❌ YouTube API error while inserting into playlist.")
        print(e)
        raise


if __name__ == "__main__":
    main()
