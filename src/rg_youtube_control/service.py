from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from .comment_rules import classify
from .config import DEFAULT_MAX_AUTO_REPLIES_PER_DAY, SAFE_AUTO_CATEGORIES
from .db import mark_replied, upsert_comment, upsert_video
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
        result = audit(snippet.get("description", ""), snippet.get("tags", []))
        row = {
            "video_id": item["id"],
            "channel_id": snippet.get("channelId"),
            "title": snippet.get("title", ""),
            "published_at": snippet.get("publishedAt"),
            "privacy_status": status.get("privacyStatus"),
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

def _today_auto_reply_count(conn: sqlite3.Connection) -> int:
    prefix = datetime.now(timezone.utc).date().isoformat() + "%"
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM comments "
        "WHERE status='replied' AND replied_at LIKE ? AND category IN ('thanks','links','donate','schedule')",
        (prefix,),
    ).fetchone()
    return int(row["n"] if row else 0)

def scan_comments(
    client: YouTubeClient,
    conn: sqlite3.Connection,
    video_ids: list[str],
    auto_reply: bool = False,
    max_auto_replies: int = DEFAULT_MAX_AUTO_REPLIES_PER_DAY,
) -> dict[str, int]:
    channel_id = client.my_channel()["id"]
    stats = {"seen": 0, "queued": 0, "auto_replied": 0, "already_replied": 0}
    auto_count = _today_auto_reply_count(conn)

    for video_id in video_ids:
        for thread in client.comment_threads(video_id, limit=100):
            top = thread["snippet"]["topLevelComment"]
            snippet = top["snippet"]
            author_id = snippet.get("authorChannelId", {}).get("value")
            if author_id == channel_id:
                continue

            text = snippet.get("textOriginal") or snippet.get("textDisplay") or ""
            decision = classify(text)
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
                "reply_text": decision.reply,
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
            if current and current["status"] == "replied":
                continue

            can_auto = (
                auto_reply
                and decision.auto_allowed
                and decision.category in SAFE_AUTO_CATEGORIES
                and decision.reply
                and auto_count < max_auto_replies
            )
            if can_auto:
                client.reply(top["id"], decision.reply)
                mark_replied(conn, top["id"], decision.reply)
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