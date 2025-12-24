import os
import random
import re
from typing import List, Optional, Dict, Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request


# =========================
# CONFIG (edit if you want)
# =========================

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# Minimum duration to accept (minutes)
MIN_DURATION_MINUTES = 15

# Search pool: we try multiple queries and multiple candidates
MAX_SEARCH_RESULTS = 20
MAX_CANDIDATES_TO_CHECK = 25

# Avoid these words in titles (typical low-quality / shorts / edits)
BAD_TITLE_PATTERNS = [
    r"\bshorts?\b",
    r"#shorts?",
    r"\btiktok\b",
    r"\breels?\b",
    r"\bedited\b",
    r"\bspeed\s*up\b",
    r"\bslowed\b",
    r"\bmeme\b",
]

# Prefer these reciters (must match title or channel)
RECITERS = [
    "Abdul Rahman Al-Sudais",
    "Mishary Rashid Alafasy",
    "Maher Al Muaiqly",
    "Saad Al Ghamdi",
]

# Topics you want (add/remove)
TOPICS = [
    "Surah Al-Kahf",
    "Surah Yasin",
    "Surah Al-Mulk",
    "Surah Ar-Rahman",
    "Surah Al-Baqarah",
    "Surah Al-Kahf Friday",
    "Quran recitation",
]

# Optional: add Arabic keywords to improve “proper recitation” results
AR_KEYWORDS = ["سورة", "تلاوة", "القرآن", "الشيخ"]


# =========================
# Helpers
# =========================

def load_youtube_client() -> Any:
    if not os.path.exists("token.json"):
        raise FileNotFoundError("token.json not found. GitHub Actions must restore it before running this script.")

    creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return build("youtube", "v3", credentials=creds)


def iso8601_to_seconds(duration: str) -> int:
    """
    Convert ISO8601 duration like PT24M47S into seconds.
    """
    # PT#H#M#S
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", duration)
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mm = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 3600 + mm * 60 + s


def title_is_bad(title: str) -> bool:
    t = title.lower()
    return any(re.search(pat, t, flags=re.IGNORECASE) for pat in BAD_TITLE_PATTERNS)


def reciter_matches(title: str, channel_title: str) -> bool:
    hay = f"{title} {channel_title}".lower()
    return any(r.lower() in hay for r in RECITERS)


def playlist_contains_video(youtube: Any, playlist_id: str, video_id: str) -> bool:
    page_token = None
    while True:
        resp = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=page_token
        ).execute()

        for item in resp.get("items", []):
            if item.get("contentDetails", {}).get("videoId") == video_id:
                return True

        page_token = resp.get("nextPageToken")
        if not page_token:
            return False


def add_video_to_playlist(youtube: Any, playlist_id: str, video_id: str) -> None:
    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        },
    ).execute()


def search_candidates(youtube: Any, query: str) -> List[str]:
    """
    Search for videos and return a list of video IDs.
    We use videoDuration=medium/long by doing two passes: long first, then medium.
    """
    video_ids: List[str] = []

    # Pass 1: LONG (>20 mins)
    for dur in ["long", "medium"]:
        resp = youtube.search().list(
            part="id,snippet",
            q=query,
            type="video",
            maxResults=MAX_SEARCH_RESULTS,
            order="relevance",
            videoDuration=dur,
            safeSearch="none",
        ).execute()

        for item in resp.get("items", []):
            vid = item.get("id", {}).get("videoId")
            if vid:
                video_ids.append(vid)

        if video_ids:
            break

    # De-dup while preserving order
    seen = set()
    out = []
    for v in video_ids:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def fetch_video_details(youtube: Any, video_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Returns dict: videoId -> details {title, channelTitle, duration, privacyStatus}
    """
    details: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        resp = youtube.videos().list(
            part="snippet,contentDetails,status",
            id=",".join(chunk)
        ).execute()

        for item in resp.get("items", []):
            vid = item.get("id")
            snippet = item.get("snippet", {})
            status = item.get("status", {})
            cd = item.get("contentDetails", {})

            details[vid] = {
                "title": snippet.get("title", ""),
                "channelTitle": snippet.get("channelTitle", ""),
                "duration": cd.get("duration", "PT0S"),
                "privacyStatus": status.get("privacyStatus", ""),
            }

    return details


def pick_best_video(
    youtube: Any,
    playlist_id: str,
    candidates: List[str]
) -> Optional[str]:
    """
    Filter and pick a good video.
    """
    if not candidates:
        return None

    candidates = candidates[:MAX_CANDIDATES_TO_CHECK]
    info_map = fetch_video_details(youtube, candidates)

    min_seconds = MIN_DURATION_MINUTES * 60

    for vid in candidates:
        info = info_map.get(vid)
        if not info:
            continue

        title = info["title"]
        channel = info["channelTitle"]
        privacy = info["privacyStatus"]
        seconds = iso8601_to_seconds(info["duration"])

        # Skip private/unlisted/anything not public
        if privacy != "public":
            continue

        # Skip too short
        if seconds < min_seconds:
            continue

        # Skip bad/shorts titles
        if title_is_bad(title):
            continue

        # Must match preferred reciters (to avoid random channels)
        if not reciter_matches(title, channel):
            continue

        # Avoid duplicates already in playlist
        if playlist_contains_video(youtube, playlist_id, vid):
            continue

        return vid

    return None


# =========================
# Main
# =========================

def main() -> None:
    playlist_id = os.environ.get("PLAYLIST_ID"
