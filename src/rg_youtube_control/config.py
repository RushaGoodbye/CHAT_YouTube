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
        # must start with exactly two backslashes, with single separators
        # between every path component.
        parts = [part for part in text.strip("\\").split("\\") if part]
        return "\\\\" + "\\".join(parts)

    return text

DEFAULT_SCAN_MINUTES = 10
DEFAULT_MAX_AUTO_REPLIES_PER_DAY = 30
DEFAULT_MAX_AUTO_REPLIES_PER_SCAN = 5
DEFAULT_AUTO_REPLY_MAX_AGE_HOURS = 24
DEFAULT_SAFE_AUTOPILOT_INTERVAL_MINUTES = 60
DEFAULT_SAFE_AUTOPILOT_DAILY_LIMIT = 30
SAFE_AUTO_CATEGORIES = {"thanks", "links", "donate", "schedule"}
DEFAULT_REPLY_TEMPLATES = {
    "thanks": "Дякуємо за підтримку! 💙💛",
    "links": f"Усі актуальні посилання проєкту тут: {PROJECT_LINKS_URL}",
    "donate": f"Дякуємо за підтримку! Усі варіанти донату для ЗСУ тут: {DONATE_URL}",
    "schedule": "Стріми виходять Пн, Ср, Пт і Сб з 21:00 до 00:00. До зустрічі в ефірі 🙂",
}

DEFAULT_REPLY_VARIANTS = {
    "thanks": (
        "Дякуємо за підтримку! 💙💛",
        "Щиро дякуємо за підтримку! 💙💛",
        "Дякуємо, що ви з нами! 💙💛",
    ),
    "links": (
        f"Усі актуальні посилання проєкту тут: {PROJECT_LINKS_URL}",
        f"Актуальні посилання РАША ГУДБАЙ: {PROJECT_LINKS_URL}",
        f"Усе актуальне по проєкту зібрано тут: {PROJECT_LINKS_URL}",
    ),
    "donate": (
        f"Дякуємо за підтримку! Усі варіанти донату для ЗСУ тут: {DONATE_URL}",
        f"Підтримати наші збори для ЗСУ можна тут: {DONATE_URL}",
        f"Усі актуальні варіанти підтримки ЗСУ: {DONATE_URL}",
    ),
    "schedule": (
        "Стріми виходять Пн, Ср, Пт і Сб з 21:00 до 00:00. До зустрічі в ефірі 🙂",
        "Зустрічаємось у прямому ефірі Пн, Ср, Пт і Сб з 21:00 до 00:00 🙂",
        "Наш розклад: Пн, Ср, Пт і Сб, з 21:00 до 00:00. До зустрічі!",
    ),
}

def app_data_dir() -> Path:
    fallback = Path.home() / "AppData" / "Local"
    base = Path(os.getenv("LOCALAPPDATA", str(fallback)))
    return base / "RGYouTubeControl"