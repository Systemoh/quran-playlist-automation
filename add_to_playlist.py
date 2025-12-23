"""
add_to_playlist.py (CLEAN)

Goal:
- Find Quran videos via YouTube Search (broad + boosted reciters/topics)
- Prefer known reciters/topics (scoring)
- Add the FOUND video(s) directly to YOUR playlist
- NO downloading (no yt-dlp)
- NO uploading (no ffmpeg)
"""
print("=== VERSION CHECK: token.json script ===")

import os
from typing import List, Dict, Tuple
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# =========================
# CONFIG
# =========================
# Playlist-only permissions (no upload)
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

PLAYLIST_ID = os.getenv("PLAYLIST_ID", "PLqJjpOfBttCUcmlGBdzpEYhGTMYduINkf")

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

# Broad search terms: NOT restricted to your reciters
BROAD_QUERIES = [
    "quran recitation",
    "quran recitation beautiful voice",
    "surah yasin recitation",
    "surah al kahf recitation",
]

# How many new videos to add per run
MAX_TO_ADD = 3


# =========================
# AUTH
# =========================
def get_youtube():
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
           return build("youtube", "v3", credentials=creds)

# =========================
# PLAYLIST HELPERS
# =========================
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
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": video_id
                }
            }
        }
    ).execute()
    print(f"✅ Added to playlist: videoId={video_id} | playlistItemId={resp.get('id')}")


# =========================
# SEARCH + SCORING
# =========================
def search_videos(youtube, query: str, max_results: int = 25) -> Dict:
    return youtube.search().list(
        part="snippet",
        q=query,
        type="video",
        maxResults=max_results
    ).execute()


def collect_candidates(youtube, max_total: int = 80) -> List[Dict]:
    """
    Collect candidates from:
      1) BROAD searches (general)
      2) BOOSTED searches using RECITERS + TOPICS (preference)
    Dedupe by videoId.
    """
    seen = set()
    results: List[Dict] = []

    # 1) Broad searches
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

    # 2) Boosted searches (not exclusive)
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
    """
    Higher score = more preferred.
    Preference is based on reciter/topic appearing in title/channel,
    but still allows any video (broad results).
    """
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
    """
    Returns a list of (score, item) not already in playlist, sorted best-first.
    """
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


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    youtube = get_youtube()

    picks = pick_best_candidates(youtube, MAX_TO_ADD)
    if not picks:
        raise RuntimeError("No new videos found (all candidates already in playlist).")

    for score, item in picks:
        vid = item["id"]["videoId"]
        title = item["snippet"]["title"]
        channel = item["snippet"]["channelTitle"]

        print(f"Selected (score={score}): {title} | Channel: {channel} | videoId: {vid}")
        add_video_to_playlist(youtube, vid)

    print("✅ Done. Added videos directly to playlist (no download, no upload).")
