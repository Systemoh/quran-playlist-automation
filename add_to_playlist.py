import os
import random
import re
from typing import Any, Set, List

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request


# =========================
# CONFIG
# =========================

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# Minimum duration to accept (minutes)
MIN_DURATION_MINUTES = 15

# How many search results to consider
MAX_SEARCH_RESULTS = 25
MAX_CANDIDATES_TO_CHECK = 30

# Avoid these words in titles (typical low-quality / shorts / edits)
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
    r"\b1-?11\b",           # catches "1-11" style partial clip titles
    r"\bpart\s*\d+\b",
]

# ✅ Expanded list of well-known reciters (English spellings vary, so we also match partials)
RECITERS = [
    # Saudi / Haramain
    "Abdul Rahman Al-Sudais",
    "Abdurrahman Al Sudais",
    "Saud Al-Shuraim",
    "Saud Al Shuraim",
    "Maher Al Muaiqly",
    "Maher Al-Muaiqly",
    "Yasser Al-Dosari",
    "Yasser Al Dosari",
    "Abdullah Al-Juhany",
    "Abdullah Al Juhany",
    "Saleh Al Talib",
    "Saleh Al-Talib",
    "Bandar Balilah",
    "Abdullah Basfar",
    "Nasser Al Qatami",

    # Popular worldwide
    "Mishary Rashid Alafasy",
    "Mishary Alafasy",
    "Saad Al Ghamdi",
    "Saad Al-Ghamdi",
    "Abu Bakr Al-Shatri",
    "Abu Bakr Al Shatri",
    "Hani Ar-Rifai",
    "Hani Al Rifai",
    "Muhammad Ayyub",
    "Mohammed Ayyub",
    "Ali Jaber",
    "Sheikh Ali Jaber",
    "Idris Abkar",
    "Minshawi",
    "Al-Minshawi",
    "Mahmoud Khalil Al-Husary",
    "Al-Husary",
    "Abdul Basit",
    "AbdulBasit",
    "Abdul Basit Abdus Samad",
]

# Topics / searches
TOPICS = [
    "Surah Al-Kahf",
    "Surah Yasin",
    "Surah Al-Mulk",
    "Surah Ar-Rahman",
    "Surah Al-Baqarah",
    "Surah Al-Waqiah",
    "Surah Al-Sajdah",
    "Juz Amma Quran recitation",
    "Quran recitation full",
]

# Optional Arabic keywords to improve “proper recitation” results
AR_KEYWORDS = ["سورة", "تلاوة", "القرآن", "الشيخ", "قراءة"]


# =========================
# Helpers
# =========================

def load_youtube_client() -> Any:
    if not os.path.exists("token.json"):
        raise FileNotFoundError("token.json not found. GitHub Actions must restore it before running this script.")

    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return build("youtube", "v3", credentials=creds)


def iso8601_to_seconds(duration: str) -> int:
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

    for r in RECITERS:
        if r.lower() in hay:
            return True

    partials = [
        "sudais", "shuraim", "muaiqly", "dosari", "juhany", "talib",
        "alafasy", "afasy", "ghamdi", "shatri", "rifai", "ayyub",
        "ali jaber", "idris abkar", "minshawi", "husary", "abdul basit",
        "qatami", "basfar", "balilah"
    ]
    return any(p in hay for p in partials)


def get_playlist_video_ids(youtube: Any, playlist_id: str) -> Set[str]:
    ids: Set[str] = set()
    page_token = None
    while True:
        resp = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=page_token
        ).execute()

        for item in resp.get("items", []):
            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                ids.add(vid)

        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


def add_video_to_playlist(youtube: Any, playlist_id: str, video_id: str) -> None:
    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": video_id
                },
            }
        }
    ).execute()


def search_candidates(youtube: Any) -> List[str]:
    """Return a list of candidate videoIds (may include duplicates, filtered later)."""
    q = random.choice(TOPICS)
    # Add some Arabic keywords sometimes to bias results toward real recitations
    if random.random() < 0.5:
        q = f"{q} {random.choice(AR_KEYWORDS)}"

    resp = youtube.search().list(
        part="snippet",
        q=q,
        type="video",
        maxResults=MAX_SEARCH_RESULTS,
        videoEmbeddable="true",
        safeSearch="strict"
    ).execute()

    ids: List[str] = []
    for item in resp.get("items", []):
        vid = (item.get("id") or {}).get("videoId")
        if vid:
            ids.append(vid)
    return ids


def get_video_details(youtube: Any, video_id: str) -> dict:
    resp = youtube.videos().list(
        part="contentDetails,snippet",
        id=video_id
    ).execute()
    items = resp.get("items", [])
    return items[0] if items else {}


def is_good_video(video: dict) -> bool:
    snip = video.get("snippet", {})
    cd = video.get("contentDetails", {})
    title = snip.get("title", "")
    channel_title = snip.get("channelTitle", "")
    duration = cd.get("duration", "PT0S")

    if not title:
        return False
    if title_is_bad(title):
        return False
    if not reciter_matches(title, channel_title):
        return False

    seconds = iso8601_to_seconds(duration)
    if seconds < MIN_DURATION_MINUTES * 60:
        return False

    return True


def main() -> None:
    playlist_id = os.getenv("PLAYLIST_ID", "").strip()
    if not playlist_id:
        raise ValueError("PLAYLIST_ID env var is missing. Add it as a GitHub Secret and pass it in workflow env.")

    youtube = load_youtube_client()

    # Load existing playlist IDs once
    existing_ids = get_playlist_video_ids(youtube, playlist_id)

    # Search + evaluate candidates
    candidates = search_candidates(youtube)
    random.shuffle(candidates)

    checked = 0
    for vid in candidates:
        if vid in existing_ids:
            continue

        checked += 1
        if checked > MAX_CANDIDATES_TO_CHECK:
            break

        video = get_video_details(youtube, vid)
        if not video:
            continue

        if is_good_video(video):
            add_video_to_playlist(youtube, playlist_id, vid)
            title = (video.get("snippet") or {}).get("title", "")
            print(f"✅ Added: {vid} | {title}")
            return

    print("⚠️ No suitable video found today (filtered or duplicates).")


if __name__ == "__main__":
    try:
        main()
    except HttpError as e:
        # Show helpful API error message
        print("YouTube API error:", e)
        raise
