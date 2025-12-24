import os
from typing import List, Dict, Tuple
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

PLAYLIST_ID = os.getenv("PLAYLIST_ID")

RECITERS = [
    "Abdul Rahman Al-Sudais",
    "Mishary Rashid Alafasy",
    "Maher Al Muaiqly",
    "Saad Al Ghamdi",
]

TOPICS = [
    "quran recitation",
    "surah al rahman",
    "surah yasin",
    "surah al kahf",
]

BROAD_QUERIES = [
    "quran recitation",
    "quran recitation beautiful voice",
    "surah yasin recitation",
    "surah al kahf recitation",
]

MAX_TO_ADD = 3

def get_youtube():
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open("token.json", "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)

def playlist_contains(youtube, video_id: str) -> bool:
    page_token = None
    while True:
        resp = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=PLAYLIST_ID,
            maxResults=50,
            pageToken=page_token
        ).execute()

        for item in resp.get("items", []):
            if item["contentDetails"]["videoId"] == video_id:
                return True

        page_token = resp.get("nextPageToken")
        if not page_token:
            return False

def add_video_to_playlist(youtube, video_id: str):
    resp = youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": PLAYLIST_ID,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        }
    ).execute()
    print(f"✅ Added: {video_id} | playlistItemId={resp.get('id')}")

def search_videos(youtube, query: str, max_results: int = 25) -> Dict:
    return youtube.search().list(
        part="snippet",
        q=query,
        type="video",
        maxResults=max_results
    ).execute()

def collect_candidates(youtube, max_total: int = 120) -> List[Dict]:
    seen = set()
    results: List[Dict] = []

    for q in BROAD_QUERIES:
        resp = search_videos(youtube, q, max_results=25)
        for it in resp.get("items", []):
            vid = it.get("id", {}).get("videoId")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            results.append(it)
            if len(results) >= max_total:
                return results

    for r in RECITERS:
        for t in TOPICS:
            q = f"{r} {t}"
            resp = search_videos(youtube, q, max_results=10)
            for it in resp.get("items", []):
                vid = it.get("id", {}).get("videoId")
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                results.append(it)
                if len(results) >= max_total:
                    return results

    return results

def score_item(item: Dict) -> int:
    s = item.get("snippet", {})
    title = (s.get("title") or "").lower()
    channel = (s.get("channelTitle") or "").lower()

    score = 0
    for r in RECITERS:
        rl = r.lower()
        if rl in title:
            score += 5
        if rl in channel:
            score += 3
    for t in TOPICS:
        tl = t.lower()
        if tl in title:
            score += 2
    return score

def pick_best_candidates(youtube, max_to_add: int) -> List[Tuple[int, Dict]]:
    candidates = collect_candidates(youtube, max_total=120)
    print(f"Collected {len(candidates)} candidates.")

    ranked: List[Tuple[int, Dict]] = []
    for item in candidates:
        vid = item.get("id", {}).get("videoId")
        if not vid:
            continue
        if playlist_contains(youtube, vid):
            continue
        ranked.append((score_item(item), item))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[:max_to_add]

if __name__ == "__main__":
    if not PLAYLIST_ID:
        raise RuntimeError("PLAYLIST_ID is missing. Add it as a GitHub Secret and pass it via env.")

    youtube = get_youtube()
    picks = pick_best_candidates(youtube, MAX_TO_ADD)

    if not picks:
        raise RuntimeError("No new videos found (all candidates already in playlist).")

    for score, item in picks:
        vid = item["id"]["videoId"]
        title = item["snippet"]["title"]
        channel = item["snippet"]["channelTitle"]
        print(f"Selected (score={score}): {title} | {channel} | {vid}")
        add_video_to_playlist(youtube, vid)

    print("✅ Done.")
