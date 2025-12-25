import os
import random
import re
from typing import Any, Optional, List, Set, Tuple

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# ===== DAILY TARGET =====
VIDEOS_PER_RUN = 10

# Minimum duration to accept (minutes)
MIN_DURATION_MINUTES = 15

# Search tuning
MAX_SEARCH_RESULTS = 25
MAX_CANDIDATES_TO_CHECK = 60   # per search query
MAX_TOTAL_ATTEMPTS = 40        # overall attempts to find enough videos

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

RECITERS = [
    # Haramain / Saudi
    "Abdul Rahman Al-Sudais",
    "Saud Al-Shuraim",
    "Maher Al Muaiqly",
    "Abdullah Awad Al-Juhany",
    "Yasser Al-Dosari",
    "Bandar Baleela",
    # Popular international
    "Mishary Rashid Alafasy",
    "Saad Al Ghamdi",
    "Abdul Basit Abdus Samad",
    "Mahmoud Khalil Al-Husary",
    "Mohamed Siddiq El Minshawi",
    "Mustafa Ismail",
    "Nasser Al Qatami",
    "Ahmed Al Ajmi",
    "Hani Ar-Rifai",
    "Ali Jaber",
    # Modern / younger audience
    "Omar Hisham Al Arabi",
    "Islam Sobhi",
    "Hassan Saleh",
    "Idris Abkar",
    "Fares Abbad",
    # Calm / slow style
    "Salah Bukhatir",
    "Muhammad Luhaidan",
    "Abdullah Basfar",
]

TOPICS = [
    # General
    "quran recitation",
    "holy quran full recitation",
    "beautiful quran recitation",
    "quran tilawat",
    # Long-form / listening
    "quran recitation for sleep",
    "quran recitation for relaxation",
    "calm quran recitation",
    "slow quran recitation",
    # Surah-based
    "surah al baqarah",
    "surah al kahf",
    "surah yasin",
    "surah ar rahman",
    "surah al waqiah",
    "surah maryam",
    "surah al mulk",
    "surah al anbiya",
    # Juz / structured
    "juz amma recitation",
    "juz tabarak recitation",
    # Emotional / spiritual
    "emotional quran recitation",
    "beautiful voice quran",
    "heart touching quran recitation",
    # Ramadan / night prayers
    "taraweeh recitation",
    "qiyam ul layl recitation",
]


def load_youtube() -> Any:
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def is_bad_title(title: str) -> bool:
    return any(re.search(p, title, flags=re.IGNORECASE) for p in BAD_TITLE_PATTERNS)


def playlist_video_ids(yt: Any, playlist_id: str) -> Set[str]:
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
    resp = yt.videos().list(part="contentDetails,status", id=video_id, maxResults=1).execute()
    items = resp.get("items", [])
    if not items:
        return None

    status = items[0].get("status", {})
    if status.get("privacyStatus") == "private":
        return None

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


def pick_one_new_video(
    yt: Any,
    existing: Set[str],
    picked_this_run: Set[str],
) -> Optional[Tuple[str, str, int, str]]:
    """Return (video_id, title, minutes, query_used) or None."""
    reciter = random.choice(RECITERS)
    topic = random.choice(TOPICS)
    query = f"{reciter} {topic}"

    candidates = search_candidates(yt, query)
    random.shuffle(candidates)

    checked = 0
    for vid, title in candidates:
        if checked >= MAX_CANDIDATES_TO_CHECK:
            break
        checked += 1

        if vid in existing or vid in picked_this_run:
            continue
        if is_bad_title(title):
            continue

        mins = video_duration_minutes(yt, vid)
        if mins is None:
            continue
        if mins < MIN_DURATION_MINUTES:
            continue

        return vid, title, mins, query

    return None


def main() -> None:
    playlist_id = os.getenv("PLAYLIST_ID")
    if not playlist_id:
        raise RuntimeError("PLAYLIST_ID missing")

    yt = load_youtube()

    me = yt.channels().list(part="snippet", mine=True).execute()
    channel_title = me["items"][0]["snippet"]["title"] if me.get("items") else "UNKNOWN"
    print("✅ Authenticated channel:", channel_title)
    print("📌 Target PLAYLIST_ID:", playlist_id)

    existing = playlist_video_ids(yt, playlist_id)
    print(f"📚 Playlist currently contains {len(existing)} videos")

    added = 0
    attempts = 0
    picked_this_run: Set[str] = set()

    while added < VIDEOS_PER_RUN and attempts < MAX_TOTAL_ATTEMPTS:
        attempts += 1

        pick = pick_one_new_video(yt, existing, picked_this_run)
        if not pick:
            continue

        video_id, title, mins, query = pick
        print(f"🎯 Candidate {added+1}/{VIDEOS_PER_RUN}: {title} ({mins} min) — {video_id}")
        print(f"   via: {query}")

        try:
            add_to_playlist(yt, playlist_id, video_id)
            print("✅ Added.")
            added += 1
            picked_this_run.add(video_id)
            existing.add(video_id)  # so we don't pick it again
        except HttpError as e:
            msg = str(e)
            # Skip known "not usable" cases without failing the workflow
            if "videoNotFound" in msg or "Video not found" in msg:
                print(f"⚠️ Skipping (videoNotFound): {video_id}")
                picked_this_run.add(video_id)
                continue
            if "quotaExceeded" in msg or "Quota exceeded" in msg:
                print("⚠️ Quota exceeded. Stopping early for today.")
                break

            print("❌ YouTube API error while inserting into playlist.")
            print(e)
            raise

    print(f"✅ Done. Added {added}/{VIDEOS_PER_RUN} videos (attempts={attempts}).")


if __name__ == "__main__":
    main()
