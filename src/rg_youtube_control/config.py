import os
from pathlib import Path

APP_NAME = "RG YouTube Control"
APP_SLUG = "rg-youtube-control"
MAIN_CHANNEL_ID = "UCzaBfIZNcZcFxv4N854UIVQ"
LIVE_CHANNEL_ID = "UCTZxf8k7ADN4XXqUVixBloA"
KNOWN_CHANNELS = {
    MAIN_CHANNEL_ID: "РАША ГУДБАЙ",
    LIVE_CHANNEL_ID: "РАША ГУДБАЙ LIVE",
}
PROFILE_TARGETS = {
    "main": MAIN_CHANNEL_ID,
    "live": LIVE_CHANNEL_ID,
}
PROFILE_LABELS = {
    "main": "РАША ГУДБАЙ",
    "live": "РАША ГУДБАЙ LIVE",
}

PROJECT_LINKS_URL = "https://links.rginfoua.pp.ua/"
DONATE_URL = "https://donate.rginfoua.pp.ua/"
OLD_PROJECT_LINKS = "https://rg-links-d9e.pages.dev/"
OLD_DONATE_LINK = "https://rg-donates.pages.dev/"

DEFAULT_NAS_TRANSCRIPTS_PATH = r"\\AlexLosServer\RG_AUTO_EDIT\YOUTUBE_CONTROL\TRANSCRIPTS"
DEFAULT_NAS_PACKAGES_PATH = r"\\AlexLosServer\RG_AUTO_EDIT\YOUTUBE_CONTROL\PACKAGES"
PACKAGE_BRIDGE_URL = "http://AlexLosServer:8790"


def normalize_nas_unc_path(value: str | None, default: str) -> str:
    text = (value or "").strip().replace("/", "\\")
    if not text:
        text = default

    if ":" not in text and "\\" in text:
        # Repair malformed UNC paths from older builds. Windows SMB paths
        # must start with exactly two backslashes, not three or four.
        return "\\\\" + text.lstrip("\\")

    return text

DEFAULT_SCAN_MINUTES = 10
DEFAULT_MAX_AUTO_REPLIES_PER_DAY = 20
DEFAULT_MAX_AUTO_REPLIES_PER_SCAN = 3
DEFAULT_AUTO_REPLY_MAX_AGE_HOURS = 72
SAFE_AUTO_CATEGORIES = {"thanks", "links", "donate", "schedule"}
DEFAULT_REPLY_TEMPLATES = {
    "thanks": "Дякуємо за підтримку! 💙💛",
    "links": f"Усі актуальні посилання проєкту: {PROJECT_LINKS_URL}",
    "donate": f"Дякуємо за підтримку! Усі варіанти донейту: {DONATE_URL}",
    "schedule": f"Актуальний розклад і всі посилання проєкту: {PROJECT_LINKS_URL}",
}

def app_data_dir() -> Path:
    fallback = Path.home() / "AppData" / "Local"
    base = Path(os.getenv("LOCALAPPDATA", str(fallback)))
    return base / "RGYouTubeControl"