from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

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
    seen_video_ids: set[str] = set()
    for item in items:
        video_id = str(item.get("id") or "")
        if not video_id or video_id in seen_video_ids:
            continue
        seen_video_ids.add(video_id)
        snippet = item.get("snippet", {})
        status = item.get("status", {})
        stats = item.get("statistics", {})
        content = item.get("contentDetails", {})
        result = audit(snippet.get("description", ""), snippet.get("tags", []))
        row = {
            "video_id": video_id,
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

    embedded = thread.get("replies", {}).get("comments", []) or []
    for reply in embedded:
        author = reply.get("snippet", {}).get("authorChannelId", {}).get("value")
        if author == channel_id:
            return True

    # commentThreads.list(part="replies") already includes available replies.
    # Only make an extra comments.list call when YouTube reports more replies
    # than were embedded in the thread payload.
    if len(embedded) >= total:
        return False

    top_id = thread["snippet"]["topLevelComment"]["id"]
    for reply in client.replies(top_id):
        author = reply.get("snippet", {}).get("authorChannelId", {}).get("value")
        if author == channel_id:
            return True
    return False


YOUTUBE_DAILY_QUOTA_DEFAULT = 10000
VIDEO_UPDATE_COST = 50
COMMENT_REPLY_COST = 50

def _quota_day() -> str:
    try:
        return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()

def _quota_key(name: str) -> str:
    return f"youtube_quota_{name}_{_quota_day()}"

def today_quota_units(conn: sqlite3.Connection) -> int:
    return int(get_setting(conn, _quota_key("units"), "0") or 0)

def record_quota_units(conn: sqlite3.Connection, units: int) -> int:
    total = today_quota_units(conn) + max(0, int(units))
    set_setting(conn, _quota_key("units"), str(total))
    return total

def quota_exhausted(conn: sqlite3.Connection) -> bool:
    return get_setting(conn, _quota_key("exhausted"), "0") == "1"

def mark_quota_exhausted(conn: sqlite3.Connection) -> None:
    set_setting(conn, _quota_key("exhausted"), "1")

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
    record_quota_units(conn, COMMENT_REPLY_COST)
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



def _validated_reply_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Текст відповіді порожній.")
    if len(text) > 10000:
        raise ValueError("Текст відповіді перевищує 10 000 символів.")
    return text


def _is_quota_error(exc: Exception) -> bool:
    reason = _http_error_reason(exc) if isinstance(exc, HttpError) else ""
    text = str(exc).casefold()
    return (
        reason.casefold() == "quotaexceeded"
        or "quotaexceeded" in text
        or "quota exceeded" in text
    )

def scan_comments(
    client: YouTubeClient,
    conn: sqlite3.Connection,
    video_ids: list[str],
    auto_reply: bool = False,
    max_auto_replies: int = DEFAULT_MAX_AUTO_REPLIES_PER_DAY,
    max_auto_replies_per_scan: int = DEFAULT_MAX_AUTO_REPLIES_PER_SCAN,
    max_auto_age_hours: int = DEFAULT_AUTO_REPLY_MAX_AGE_HOURS,
) -> dict[str, int]:
    stats = {
        "seen": 0,
        "queued": 0,
        "auto_replied": 0,
        "already_replied": 0,
        "skipped_disabled": 0,
        "skipped_old": 0,
        "skipped_review": 0,
        "skipped_limit": 0,
        "quota_blocked": 0,
    }
    auto_count = today_auto_reply_count(conn)

    if quota_exhausted(conn):
        stats["quota_blocked"] += 1
        return stats

    channel_key = f"youtube_channel_id_{getattr(client, \"profile\", \"default\")}"
    channel_id = get_setting(conn, channel_key, "").strip()
    if not channel_id:
        try:
            channel_id = client.my_channel()["id"]
            set_setting(conn, channel_key, channel_id)
        except Exception as exc:
            if _is_quota_error(exc):
                mark_quota_exhausted(conn)
                stats["quota_blocked"] += 1
                return stats
            raise

    for video_id in video_ids:
        try:
            threads = client.comment_threads(video_id, limit=100)
        except HttpError as exc:
            if exc.resp.status == 403 and _http_error_reason(exc) == "commentsDisabled":
                stats["skipped_disabled"] += 1
                continue
            if _is_quota_error(exc):
                mark_quota_exhausted(conn)
                stats["quota_blocked"] += 1
                return stats
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

            comment_id = top["id"]
            current = conn.execute(
                "SELECT status FROM comments WHERE comment_id=?", (comment_id,)
            ).fetchone()
            known_status = str(current["status"] or "") if current else ""

            # Local state is authoritative for comments the app already replied to
            # or the user explicitly ignored. Avoid a remote replies.list call.
            if known_status in {"replied", "ignored"}:
                has_reply = known_status == "replied"
            else:
                try:
                    has_reply = _own_reply_exists(client, thread, channel_id)
                except Exception as exc:
                    if _is_quota_error(exc):
                        mark_quota_exhausted(conn)
                        stats["quota_blocked"] += 1
                        return stats
                    raise

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
                and not quota_exhausted(conn)
            )
            if can_auto:
                safe_reply = _validated_reply_text(reply_text)
                try:
                    client.reply(top["id"], safe_reply)
                except Exception as exc:
                    if _is_quota_error(exc):
                        mark_quota_exhausted(conn)
                        stats["quota_blocked"] += 1
                        return stats
                    raise
                mark_replied(conn, top["id"], safe_reply)
                _record_reply(conn, auto=True)
                auto_count += 1
                stats["auto_replied"] += 1
            else:
                if auto_reply:
                    if quota_exhausted(conn):
                        stats["quota_blocked"] += 1
                    elif not recent_for_auto:
                        stats["skipped_old"] += 1
                    elif (
                        not decision.auto_allowed
                        or decision.category not in SAFE_AUTO_CATEGORIES
                    ):
                        stats["skipped_review"] += 1
                    elif (
                        auto_count >= max_auto_replies
                        or stats["auto_replied"] >= max_auto_replies_per_scan
                    ):
                        stats["skipped_limit"] += 1
                stats["queued"] += 1
    return stats

def manual_reply(
    client: YouTubeClient,
    conn: sqlite3.Connection,
    comment_id: str,
    reply_text: str,
) -> None:
    row = conn.execute(
        "SELECT status FROM comments WHERE comment_id=?",
        (comment_id,),
    ).fetchone()
    if row is not None and str(row["status"] or "") == "replied":
        raise RuntimeError("На цей коментар вже надіслано відповідь.")

    if quota_exhausted(conn):
        raise RuntimeError(
            "Денну квоту YouTube Data API вже вичерпано. "
            "Відповідь не відправлено."
        )

    safe_reply = _validated_reply_text(reply_text)
    try:
        client.reply(comment_id, safe_reply)
    except Exception as exc:
        if _is_quota_error(exc):
            mark_quota_exhausted(conn)
            raise RuntimeError(
                "Денну квоту YouTube Data API вичерпано. "
                "Відповідь не відправлено."
            ) from exc
        raise

    mark_replied(conn, comment_id, safe_reply)
    _record_reply(conn, auto=False)