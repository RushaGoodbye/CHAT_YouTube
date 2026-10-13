"""Opt-in, authenticated live research connectors for RG Media Deck.

Telegram uses user's own API ID/hash and an independent MTProto session
(credentials in Windows Credential Manager via keyring). Logging in to
Telegram Web does NOT authorize a native MTProto API session.
OpenAI Responses web_search requires a separately billed API key: a ChatGPT
Web login/subscription is NOT an OpenAI API credential.

Neither provider is called when not configured. No fake results are returned.
Calls execute on QThread workers, never Qt's media/UI thread.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from urllib.parse import urlsplit

from unified_research import normalize_query, research_prompt

SERVICE = "RGMediaDeck.OptInResearch"
MODEL = "gpt-5-mini"  # API model supported by Responses web_search


def credentials():
    import keyring
    def value(name):
        return keyring.get_password(SERVICE, name) or ""
    return {
        "telegram_api_id": value("telegram_api_id"),
        "telegram_api_hash": value("telegram_api_hash"),
        "telegram_phone": value("telegram_phone"),
        "openai_api_key": value("openai_api_key"),
    }


def save_credentials(**secrets):
    import keyring
    permitted = {"telegram_api_id", "telegram_api_hash", "telegram_phone", "openai_api_key"}
    for field, value in secrets.items():
        if field not in permitted:
            raise ValueError("Unexpected credential field")
        if value:
            keyring.set_password(SERVICE, field, str(value).strip())
        else:
            try:
                keyring.delete_password(SERVICE, field)
            except keyring.errors.PasswordDeleteError:
                pass


def telegram_settings_valid(keys: dict) -> bool:
    try:
        api_id = int(keys.get("telegram_api_id", ""))
    except (TypeError, ValueError):
        return False
    return (api_id > 0 and bool(re.fullmatch(r"[a-fA-F0-9]{32}",
            keys.get("telegram_api_hash", ""))) and
            bool(re.fullmatch(r"\+?[0-9]{7,16}", keys.get("telegram_phone", ""))))


def telegram_session(profile: Path) -> str:
    folder = Path(profile)
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder / "telegram_research")


async def telegram_auth(action: str, keys: dict, profile: Path,
                        code: str = "", code_hash: str = "",
                        password: str = "") -> dict:
    """Send Telegram confirmation code, sign in, or respond to 2FA challenge."""
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
    if not telegram_settings_valid(keys):
        raise ValueError("Нужно указать Telegram API ID, API Hash и телефон")
    client = TelegramClient(telegram_session(profile),
                            int(keys["telegram_api_id"]),
                            keys["telegram_api_hash"],
                            request_retries=1, connection_retries=1,
                            timeout=15)
    await client.connect()
    try:
        if action == "request":
            if await client.is_user_authorized():
                return {"status": "authorized"}
            sent = await client.send_code_request(keys["telegram_phone"])
            return {"status": "code_sent", "code_hash": sent.phone_code_hash}
        if action == "confirm":
            try:
                await client.sign_in(phone=keys["telegram_phone"], code=code,
                                     phone_code_hash=code_hash)
            except SessionPasswordNeededError:
                return {"status": "password_required"}
            return {"status": "authorized"}
        if action == "password":
            await client.sign_in(password=password)
            return {"status": "authorized"}
        if action == "status":
            return {"status": "authorized" if await client.is_user_authorized()
                    else "not_authorized"}
        raise ValueError("Unknown Telegram login action")
    finally:
        await client.disconnect()


def post_record(message, today: datetime) -> dict | None:
    """Strictly classify photo/video and retain traceable source metadata."""
    if not getattr(message, "message", ""):
        return None
    media = getattr(message, "media", None)
    kind = ""
    if getattr(message, "photo", None):
        kind = "photo"
    elif getattr(message, "video", None):
        kind = "video"
    elif media is not None:
        doc = getattr(message, "document", None)
        mime = str(getattr(doc, "mime_type", "") or "")
        if mime.startswith("video/"):
            kind = "video"
    date = getattr(message, "date", None)
    if date is None:
        return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    chat = getattr(message, "chat", None)
    chat_name = str(getattr(chat, "title", "") or
                    getattr(chat, "username", "") or "Telegram")
    username = getattr(chat, "username", None)
    uri = (f"https://t.me/{username}/{message.id}"
           if username and message.id else "")
    return {"id": int(message.id), "chat": chat_name, "date": date.isoformat(),
            "text": str(message.message)[:5000], "kind": kind,
            "url": uri, "verified": False,
            "age_hours": round((today-date).total_seconds()/3600, 2)}


def filter_sort_posts(posts: list[dict], days: int = 7,
                      media_only: bool = False,
                      sort: str = "newest") -> list[dict]:
    """Distinct Telegram messages ordered by date; 0 days = unlimited."""
    if days not in (0, 1, 7, 30):
        raise ValueError("Time range must be 0/1/7/30 days")
    if sort not in ("newest", "oldest", "channel"):
        raise ValueError("Unknown sort mode")
    seen = set()
    seen_content = set()
    result = []
    for post in posts:
        if days and post["age_hours"] > days * 24:
            continue
        if media_only and not post["kind"]:
            continue
        key = (post["chat"], post["id"])
        # Same syndicated report across several channels should be shown
        # once. Never merge short, generic posts where matching wording is
        # insufficient evidence of an actual duplicate.
        canonical = re.sub(r"\s+", " ", re.sub(
            r"https?://\S+", "", str(post.get("text", "")).casefold())).strip()
        duplicate = canonical if len(canonical) >= 60 else None
        if key in seen or (duplicate and duplicate in seen_content):
            continue
        seen.add(key)
        if duplicate:
            seen_content.add(duplicate)
        result.append(post)
    if sort == "channel":
        return sorted(result, key=lambda x: (x["chat"].casefold(), -datetime.fromisoformat(x["date"]).timestamp()))
    return sorted(result, key=lambda x: datetime.fromisoformat(x["date"]),
                  reverse=sort == "newest")


async def telegram_search(query: str, keys: dict, profile: Path,
                          days: int = 7, limit: int = 100) -> list[dict]:
    """Native global server search of messages visible to this user only."""
    from telethon import TelegramClient
    if not telegram_settings_valid(keys):
        raise ValueError("Telegram API account not configured")
    query = normalize_query(query)
    if not query:
        return []
    client = TelegramClient(telegram_session(profile),
                            int(keys["telegram_api_id"]),
                            keys["telegram_api_hash"],
                            request_retries=1, connection_retries=1,
                            timeout=15)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise PermissionError("Сначала выполните отдельный вход в Telegram API")
        now = datetime.now(timezone.utc)
        posts = []
        async for msg in client.iter_messages(None, search=query, limit=min(limit, 150)):
            post = post_record(msg, now)
            if post:
                posts.append(post)
        return filter_sort_posts(posts, days=days)
    finally:
        await client.disconnect()


def url_citations(response) -> list[dict]:
    sources = []
    seen = set()
    for item in getattr(response, "output", ()):
        for content in getattr(item, "content", ()) or ():
            for ann in getattr(content, "annotations", ()) or ():
                if getattr(ann, "type", "") != "url_citation":
                    continue
                url = str(getattr(ann, "url", "") or "")
                if url.startswith("https://") and url not in seen:
                    sources.append({"url": url, "title": str(getattr(ann, "title", "") or url)})
                    seen.add(url)
    return sources


def ai_research(query: str, keys: dict) -> dict:
    """Billable Responses API web search, only when user opted in."""
    key = keys.get("openai_api_key", "")
    if not key or not key.startswith("sk-"):
        raise PermissionError(
            "Для AI-поиска нужен отдельный OpenAI API ключ (не подписка ChatGPT)")
    from openai import OpenAI
    client = OpenAI(api_key=key, timeout=80, max_retries=0)
    response = client.responses.create(
        model=MODEL, tools=[{"type": "web_search"}],
        include=["web_search_call.action.sources"],
        input=research_prompt(query))
    text = response.output_text or ""
    sources = url_citations(response)
    return {"query": normalize_query(query), "text": text,
            "sources": sources, "date": datetime.now(timezone.utc).isoformat(),
            "model": MODEL, "verified": bool(sources)}
