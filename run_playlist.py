import os
import random
import re
from typing import Any, Optional, List, Set, Tuple

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# Minimum duration to accept (minutes)
MIN_DURATION_MINUTES = 15

# Search tuning
MAX_SEARCH_RESULTS = 25          # results per search call
MAX_CANDIDATES_TO_CHECK = 30     # cap to avoid long runs

RECITERS = [
    "Abdul Rahman Al-Sudais",
    "Mishary Rashid Alafasy",
    "Maher Al Muaiqly",
    "Saad Al Ghamdi",
]

# Broad topics
TOPICS = [
    "quran recitation",
    "surah al rahman",
    "surah yasin",
    "surah al kahf",
]

# Avoid low-quality / shorts / edits
BAD_TITLE_PATTERNS = [
    r"\bshorts?\b",
    r"#shorts?\b",
    r"\btiktok\b",
    r"\breels?\b",
    r"\bedited\b",
    r"\bspeed\s*up\b",
    r"\bslowed\b",
    r"\bmeme\b",
    r"\bclip\b",
    r"\bstatus\b",
    r"\b1-?11\b",
]


def load_youtube() -> Any:
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def is_bad_title(title: str) -> bool:
    t = title.lower()
    return any(re.search(p, t, flags=re.IGNORECASE) for p in BAD_TITLE_PATTERNS)


def playlist_video_ids(yt: Any, playlist_id: str) -> Set[str]:
    """Fetch all videoIds already in the playlist (to avoid duplicates)."""
    ids: Set[str] = set()
    page_token = None
    while True:
        resp = yt.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()

        for item in resp.get("items", []):
            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                ids.add(vid)

        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


def video_duration_minutes(yt: Any, video_id: str) -> Optional[int]:
    """Return duration minutes if accessible, otherwise None."""
    resp = yt.videos().list(part="contentDetails,status", id=video_id, maxResults=1).execute()
    items = resp.get("items", [])
    if not items:
        return None

    status = items[0].get("status", {})
    if status.get("privacyStatus") == "private":
        return None

    # Parse ISO 8601 duration (PT#H#M#S)
    dur = items[0].get("contentDetails", {}).get("duration", "")
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur)
    if not m:
        return None
    hours = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    secs = int(m.group(3) or 0)
    total_minutes = hours * 60 + mins + (1 if secs >= 30 else 0)
    return total_minutes


def search_candidates(yt: Any, query: str) -> List[Tuple[str, str]]:
    """Return list of (videoId, title) from search results."""
    resp = yt.search().list(
        part="snippet",
        q=query,
        type="video",
        maxResults=MAX_SEARCH_RESULTS,
        safeSearch="strict",
    ).execute()

    out: List[Tuple[str, str]] = []
    for item in resp.get("items", []):
        vid = item.get("id", {}).get("videoId")
        title = item.get("snippet", {}).get("title", "")
        if vid and title:
            out.append((vid, title))
    return out


def pick_video_to_add(
    yt: Any,
    existing_ids: Set[str],
) -> Optional[Tuple[str, str, int]]:
    """
    Choose a good new video (id, title, minutes).
    Strategy: random reciter + random topic -> search -> filter.
    """
    reciter = random.choice(RECITERS)
    topic = random.choice(TOPICS)
    query = f"{reciter} {topic}"
    print(f"🔎 Search query: {query}")

    candidates = search_candidates(yt, query)

    # Shuffle to diversify results
    random.shuffle(candidates)

    checked = 0
    for vid, title in candidates:
        if checked >= MAX_CANDIDATES_TO_CHECK:
            break
        checked += 1

        if vid in existing_ids:
            continue
        if is_bad_title(title):
            continue

        mins = video_duration_minutes(yt, vid)
        if mins is None:
            continue
        if mins < MIN_DURATION_MINUTES:
            continue

        return (vid, title, mins)

    return None


def add_to_playlist(yt: Any, playlist_id: str, video_id: str) -> None:
    yt.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        },
    ).execute()


def main() -> None:
    playlist_id = os.getenv("PLAYLIST_ID")
    if not playlist_id:
        raise RuntimeError("PLAYLIST_ID missing")

    yt = load_youtube()

    # Prove which channel is authenticated
    me = yt.channels().list(part="snippet", mine=True).execute()
    channel_title = me["items"][0]["snippet"]["title"] if me.get("items") else "UNKNOWN"
    print("✅ Authenticated channel:", channel_title)
    print("📌 Target PLAYLIST_ID:", playlist_id)

    # Load existing playlist ids
    existing = playlist_video_ids(yt, playlist_id)
    print(f"📚 Playlist currently contains {len(existing)} videos")

    pick = pick_video_to_add(yt, existing)
    if not pick:
        print("⚠️ No suitable new video found in this run. (Try again later)")
        return

    video_id, title, mins = pick
    print(f"🎯 Selected: {title} ({mins} min) — {video_id}")

    try:
        add_to_playlist(yt, playlist_id, video_id)
        print("✅ Added to playlist successfully.")
    except HttpError as e:
        # Handle the specific "videoNotFound" gracefully by skipping instead of killing everything
        msg = str(e)
        if "videoNotFound" in msg or "Video not found" in msg:
            print(f"⚠️ YouTube says video not found (skipping): {video_id}")
            return
        print("❌ YouTube API error while inserting into playlist.")
        print(e)
        raise


if __name__ == "__main__":
    main()
