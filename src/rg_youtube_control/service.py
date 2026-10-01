from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from googleapiclient.errors import HttpError

from .comment_rules import classify
from .config import (
    DEFAULT_AUTO_REPLY_MAX_AGE_HOURS,
    DEFAULT_MAX_AUTO_REPLIES_PER_DAY,
    DEFAULT_MAX_AUTO_REPLIES_PER_SCAN,
    DEFAULT_REPLY_TEMPLATES,
    SAFE_AUTO_CATEGORIES,
)
from .db import get_setting, mark_replied, set_setting, upsert_comment, upsert_video
from .metadata_audit import audit
from .youtube_api import YouTubeClient

def sync_videos(
    client: YouTubeClient, conn: sqlite3.Connection, limit: int = 50
) -> list[dict[str, Any]]:
    items = client.recent_videos(limit=limit)
    rows: list[dict[str, Any]] = []
    for item in items:
        snippet = item.get("snippet", {})
        status = item.get("status", {})
        stats = item.get("statistics", {})
        content = item.get("contentDetails", {})
        result = audit(snippet.get("description", ""), snippet.get("tags", []))
        row = {
            "video_id": item["id"],
            "profile": client.profile,
            "channel_id": snippet.get("channelId"),
            "title": snippet.get("title", ""),
            "published_at": snippet.get("publishedAt"),
            "scheduled_publish_at": status.get("publishAt"),
            "privacy_status": status.get("privacyStatus"),
            "duration": content.get("duration"),
            "views": int(stats.get("viewCount") or 0),
            "audit": {"score": result.score, "issues": list(result.issues)},
        }
        upsert_video(conn, row)
        rows.append(row)
    return rows

def sync_specific_videos(
    client: YouTubeClient,
    conn: sqlite3.Connection,
    video_ids: list[str],
) -> list[dict[str, Any]]:
    items = client.video_details(video_ids)
    rows: list[dict[str, Any]] = []
    for item in items:
        snippet = item.get("snippet", {})
        status = item.get("status", {})
        stats = item.get("statistics", {})
        content = item.get("contentDetails", {})
        result = audit(snippet.get("description", ""), snippet.get("tags", []))
        row = {
            "video_id": item["id"],
            "profile": client.profile,
            "channel_id": snippet.get("channelId"),
            "title": snippet.get("title", ""),
            "published_at": snippet.get("publishedAt"),
            "scheduled_publish_at": status.get("publishAt"),
            "privacy_status": status.get("privacyStatus"),
            "duration": content.get("duration"),
            "views": int(stats.get("viewCount") or 0),
            "audit": {"score": result.score, "issues": list(result.issues)},
        }
        upsert_video(conn, row)
        rows.append(row)
    return rows

def _own_reply_exists(
    client: YouTubeClient, thread: dict[str, Any], channel_id: str
) -> bool:
    total = int(thread.get("snippet", {}).get("totalReplyCount") or 0)
    if total <= 0:
        return False
    top_id = thread["snippet"]["topLevelComment"]["id"]
    for reply in client.replies(top_id):
        author = reply.get("snippet", {}).get("authorChannelId", {}).get("value")
        if author == channel_id:
            return True
    return False

def _counter_key(name: str) -> str:
    day = datetime.now(timezone.utc).date().isoformat()
    return f"{name}_{day}"

def today_auto_reply_count(conn: sqlite3.Connection) -> int:
    return int(get_setting(conn, _counter_key("auto_replies"), "0") or 0)

def today_reply_count(conn: sqlite3.Connection) -> int:
    return int(get_setting(conn, _counter_key("replies"), "0") or 0)

def _record_reply(conn: sqlite3.Connection, auto: bool) -> None:
    total = today_reply_count(conn) + 1
    set_setting(conn, _counter_key("replies"), str(total))
    if auto:
        auto_total = today_auto_reply_count(conn) + 1
        set_setting(conn, _counter_key("auto_replies"), str(auto_total))

def _http_error_reason(exc: HttpError) -> str:
    try:
        details = exc.error_details or []
        if details and isinstance(details[0], dict):
            return str(details[0].get("reason") or "")
    except Exception:
        pass
    text = str(exc)
    if "commentsDisabled" in text:
        return "commentsDisabled"
    return ""


def scan_comments(
    client: YouTubeClient,
    conn: sqlite3.Connection,
    video_ids: list[str],
    auto_reply: bool = False,
    max_auto_replies: int = DEFAULT_MAX_AUTO_REPLIES_PER_DAY,
    max_auto_replies_per_scan: int = DEFAULT_MAX_AUTO_REPLIES_PER_SCAN,
    max_auto_age_hours: int = DEFAULT_AUTO_REPLY_MAX_AGE_HOURS,
) -> dict[str, int]:
    channel_id = client.my_channel()["id"]
    stats = {
        "seen": 0,
        "queued": 0,
        "auto_replied": 0,
        "already_replied": 0,
        "skipped_disabled": 0,
    }
    auto_count = today_auto_reply_count(conn)

    for video_id in video_ids:
        try:
            threads = client.comment_threads(video_id, limit=100)
        except HttpError as exc:
            if exc.resp.status == 403 and _http_error_reason(exc) == "commentsDisabled":
                stats["skipped_disabled"] += 1
                continue
            raise

        for thread in threads:
            top = thread["snippet"]["topLevelComment"]
            snippet = top["snippet"]
            author_id = snippet.get("authorChannelId", {}).get("value")
            if author_id == channel_id:
                continue

            text = snippet.get("textOriginal") or snippet.get("textDisplay") or ""
            decision = classify(text)
            reply_text = decision.reply
            if decision.category in SAFE_AUTO_CATEGORIES:
                reply_text = get_setting(
                    conn,
                    f"reply_template_{decision.category}",
                    DEFAULT_REPLY_TEMPLATES[decision.category],
                ).strip()
            has_reply = _own_reply_exists(client, thread, channel_id)
            status = "replied" if has_reply else "new"
            item = {
                "comment_id": top["id"],
                "video_id": video_id,
                "author": snippet.get("authorDisplayName"),
                "text": text,
                "published_at": snippet.get("publishedAt"),
                "category": decision.category,
                "status": status,
                "reply_text": reply_text,
                "raw": thread,
            }
            upsert_comment(conn, item)
            stats["seen"] += 1

            if has_reply:
                mark_replied(conn, top["id"], item.get("reply_text") or "")
                stats["already_replied"] += 1
                continue

            current = conn.execute(
                "SELECT status FROM comments WHERE comment_id=?", (top["id"],)
            ).fetchone()
            if current and current["status"] in {"replied", "ignored"}:
                continue

            published_at = snippet.get("publishedAt")
            recent_for_auto = True
            if published_at and max_auto_age_hours > 0:
                try:
                    published_dt = datetime.fromisoformat(
                        str(published_at).replace("Z", "+00:00")
                    )
                    if published_dt.tzinfo is None:
                        published_dt = published_dt.replace(tzinfo=timezone.utc)
                    recent_for_auto = published_dt >= (
                        datetime.now(timezone.utc)
                        - timedelta(hours=max_auto_age_hours)
                    )
                except ValueError:
                    recent_for_auto = False

            can_auto = (
                auto_reply
                and decision.auto_allowed
                and decision.category in SAFE_AUTO_CATEGORIES
                and reply_text
                and recent_for_auto
                and auto_count < max_auto_replies
                and stats["auto_replied"] < max_auto_replies_per_scan
            )
            if can_auto:
                client.reply(top["id"], reply_text)
                mark_replied(conn, top["id"], reply_text)
                _record_reply(conn, auto=True)
                auto_count += 1
                stats["auto_replied"] += 1
            else:
                stats["queued"] += 1
    return stats

def manual_reply(
    client: YouTubeClient,
    conn: sqlite3.Connection,
    comment_id: str,
    reply_text: str,
) -> None:
    client.reply(comment_id, reply_text)
    mark_replied(conn, comment_id, reply_text)
    _record_reply(conn, auto=False)