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

DEFAULT_SCAN_MINUTES = 10
DEFAULT_MAX_AUTO_REPLIES_PER_DAY = 80
SAFE_AUTO_CATEGORIES = {"thanks", "links", "donate", "schedule"}

def app_data_dir() -> Path:
    fallback = Path.home() / "AppData" / "Local"
    base = Path(os.getenv("LOCALAPPDATA", str(fallback)))
    return base / "RGYouTubeControl"