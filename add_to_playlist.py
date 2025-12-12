import os
import json
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/youtube"]

PLAYLIST_ID = os.environ["PLAYLIST_ID"]
TOKEN_INFO = json.loads(os.environ["TOKEN_JSON"])

creds = Credentials.from_authorized_user_info(TOKEN_INFO, SCOPES)
youtube = build("youtube", "v3", credentials=creds)

def get_existing_video_ids():
    existing = set()
    req = youtube.playlistItems().list(
        part="contentDetails",
        playlistId=PLAYLIST_ID,
        maxResults=50
    )
    while req:
        res = req.execute()
        for item in res.get("items", []):
            existing.add(item["contentDetails"]["videoId"])
        req = youtube.playlistItems().list_next(req, res)
    return existing

existing_ids = get_existing_video_ids()

search = youtube.search().list(
    q="Quran recitation",
    part="id",
    type="video",
    maxResults=10
).execute()

video_to_add = None
for item in search.get("items", []):
    vid = item["id"]["videoId"]
    if vid not in existing_ids:
        video_to_add = vid
        break

if not video_to_add:
    print("✅ No new video found (all top results already in playlist).")
    raise SystemExit(0)

youtube.playlistItems().insert(
    part="snippet",
    body={
        "snippet": {
            "playlistId": PLAYLIST_ID,
            "resourceId": {"kind": "youtube#video", "videoId": video_to_add}
        }
    }
).execute()

print("✅ Added video:", video_to_add)
