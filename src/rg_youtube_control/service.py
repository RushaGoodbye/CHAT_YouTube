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
    DEFAULT_REPLY_VARIANTS,
    SAFE_AUTO_CATEGORIES,
)
from .db import (
    get_setting,
    log_action,
    mark_replied,
    set_setting,
    upsert_comment,
    upsert_video,
)
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
READ_REQUEST_COST = 1
QUOTA_RESERVE_DEFAULT = 2500

def _quota_day() -> str:
    try:
        return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()

def current_quota_day() -> str:
    return _quota_day()


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

def _counter_key(name: str, profile: str | None = None) -> str:
    day = _quota_day()
    suffix = f"_{profile}" if profile else ""
    return f"{name}{suffix}_{day}"

def today_auto_reply_count(
    conn: sqlite3.Connection, profile: str | None = None
) -> int:
    return int(get_setting(conn, _counter_key("auto_replies", profile), "0") or 0)

def today_reply_count(
    conn: sqlite3.Connection, profile: str | None = None
) -> int:
    return int(get_setting(conn, _counter_key("replies", profile), "0") or 0)

def quota_budget_status(conn: sqlite3.Connection) -> dict[str, int | bool | str]:
    used = today_quota_units(conn)
    exhausted = quota_exhausted(conn)
    reserve = int(
        get_setting(conn, "youtube_quota_reserve_units", str(QUOTA_RESERVE_DEFAULT))
        or QUOTA_RESERVE_DEFAULT
    )
    remaining = max(0, YOUTUBE_DAILY_QUOTA_DEFAULT - used)
    spendable = max(0, remaining - reserve)
    try:
        now_pt = datetime.now(ZoneInfo("America/Los_Angeles"))
        next_day = (now_pt + timedelta(days=1)).date()
        reset_text = f"{next_day.isoformat()} 00:00 PT"
    except Exception:
        reset_text = "00:00 PT"
    return {
        "used": used,
        "remaining": remaining,
        "reserve": reserve,
        "spendable": spendable,
        "reply_capacity": spendable // COMMENT_REPLY_COST,
        "video_update_capacity": remaining // VIDEO_UPDATE_COST,
        "exhausted": exhausted,
        "reset": reset_text,
    }

def _record_reply(
    conn: sqlite3.Connection,
    auto: bool,
    profile: str | None = None,
) -> None:
    total = today_reply_count(conn, profile) + 1
    set_setting(conn, _counter_key("replies", profile), str(total))
    record_quota_units(conn, COMMENT_REPLY_COST)
    if auto:
        auto_total = today_auto_reply_count(conn, profile) + 1
        set_setting(conn, _counter_key("auto_replies", profile), str(auto_total))

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

def _reply_template_for(
    conn: sqlite3.Connection,
    profile: str,
    category: str,
    comment_id: str,
) -> str:
    profile_key = f"reply_template_{profile}_{category}"
    global_key = f"reply_template_{category}"
    custom = get_setting(conn, profile_key, "").strip()
    if not custom:
        custom = get_setting(conn, global_key, "").strip()
    default = DEFAULT_REPLY_TEMPLATES[category]
    # Preserve explicitly edited templates. Otherwise rotate safe built-in
    # variants deterministically so repeated replies do not look robotic.
    if custom and custom != default:
        return custom
    variants = DEFAULT_REPLY_VARIANTS.get(category, (default,))
    checksum = sum(ord(ch) for ch in str(comment_id))
    return variants[checksum % len(variants)]


def _thread_needs_remote_reply_lookup(thread: dict[str, Any]) -> bool:
    total = int(thread.get("snippet", {}).get("totalReplyCount") or 0)
    embedded = thread.get("replies", {}).get("comments", []) or []
    return total > len(embedded)


def scan_channel_comments(
    client: YouTubeClient,
    conn: sqlite3.Connection,
    channel_id: str,
    *,
    auto_reply: bool = False,
    max_auto_replies: int = DEFAULT_MAX_AUTO_REPLIES_PER_DAY,
    max_auto_replies_per_scan: int = DEFAULT_MAX_AUTO_REPLIES_PER_SCAN,
    max_auto_age_hours: int = DEFAULT_AUTO_REPLY_MAX_AGE_HOURS,
) -> dict[str, int]:
    profile = getattr(client, "profile", "default")
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
        "api_reads": 0,
        "known_skipped": 0,
    }
    if quota_exhausted(conn):
        stats["quota_blocked"] = 1
        return stats

    now = datetime.now(timezone.utc)
    age_cutoff = now - timedelta(hours=max_auto_age_hours)
    watermark_raw = get_setting(conn, f"comment_scan_watermark_{profile}", "")
    cutoff = age_cutoff
    if watermark_raw:
        try:
            watermark = datetime.fromisoformat(watermark_raw.replace("Z", "+00:00"))
            if watermark.tzinfo is None:
                watermark = watermark.replace(tzinfo=timezone.utc)
            overlap = watermark - timedelta(minutes=5)
            if overlap > cutoff:
                cutoff = overlap
        except ValueError:
            pass
    stop_before = cutoff.isoformat().replace("+00:00", "Z")

    try:
        threads, requests = client.channel_comment_threads(
            channel_id,
            stop_before=stop_before,
            max_pages=5,
        )
        record_quota_units(conn, requests * READ_REQUEST_COST)
        stats["api_reads"] += requests
    except Exception as exc:
        if _is_quota_error(exc):
            mark_quota_exhausted(conn)
            stats["quota_blocked"] = 1
            log_action(
                conn, profile=profile, category="квота",
                action="Сканування коментарів зупинено",
                details="YouTube API quotaExceeded",
            )
            return stats
        raise

    auto_count = today_auto_reply_count(conn, profile)
    budget = quota_budget_status(conn)

    for thread in threads:
        top = thread.get("snippet", {}).get("topLevelComment", {})
        snippet = top.get("snippet", {})
        comment_id = str(top.get("id") or "")
        if not comment_id:
            continue
        published_at = str(snippet.get("publishedAt") or "")
        try:
            published_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            if published_dt.tzinfo is None:
                published_dt = published_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            published_dt = now
        if published_dt < cutoff:
            continue

        author_id = snippet.get("authorChannelId", {}).get("value")
        if author_id == channel_id:
            continue

        video_id = str(thread.get("snippet", {}).get("videoId") or "")
        current = conn.execute(
            "SELECT status FROM comments WHERE comment_id=?", (comment_id,)
        ).fetchone()
        known_status = str(current["status"] or "") if current else ""
        if known_status in {"replied", "ignored"}:
            stats["known_skipped"] += 1
            continue

        text = snippet.get("textOriginal") or snippet.get("textDisplay") or ""
        decision = classify(text)
        reply_text = decision.reply
        if decision.category in SAFE_AUTO_CATEGORIES:
            reply_text = _reply_template_for(
                conn, profile, decision.category, comment_id
            )

        try:
            if _thread_needs_remote_reply_lookup(thread):
                record_quota_units(conn, READ_REQUEST_COST)
                stats["api_reads"] += 1
            has_reply = _own_reply_exists(client, thread, channel_id)
        except Exception as exc:
            if _is_quota_error(exc):
                mark_quota_exhausted(conn)
                stats["quota_blocked"] = 1
                return stats
            raise

        item = {
            "comment_id": comment_id,
            "video_id": video_id,
            "author": snippet.get("authorDisplayName"),
            "text": text,
            "published_at": published_at,
            "category": decision.category,
            "status": "replied" if has_reply else "new",
            "reply_text": reply_text,
            "raw": thread,
        }
        upsert_comment(conn, item)
        stats["seen"] += 1

        if has_reply:
            mark_replied(conn, comment_id, reply_text or "")
            stats["already_replied"] += 1
            continue

        recent_for_auto = published_dt >= age_cutoff
        budget = quota_budget_status(conn)
        can_auto = (
            auto_reply
            and decision.auto_allowed
            and decision.category in SAFE_AUTO_CATEGORIES
            and bool(reply_text)
            and recent_for_auto
            and auto_count < max_auto_replies
            and stats["auto_replied"] < max_auto_replies_per_scan
            and int(budget["spendable"]) >= COMMENT_REPLY_COST
            and not bool(budget["exhausted"])
        )
        if can_auto:
            safe_reply = _validated_reply_text(reply_text)
            try:
                client.reply(comment_id, safe_reply)
            except Exception as exc:
                if _is_quota_error(exc):
                    mark_quota_exhausted(conn)
                    stats["quota_blocked"] = 1
                    return stats
                raise
            mark_replied(conn, comment_id, safe_reply)
            _record_reply(conn, auto=True, profile=profile)
            auto_count += 1
            stats["auto_replied"] += 1
            log_action(
                conn,
                profile=profile,
                category="коментарі",
                action="Автовідповідь",
                details=f"{snippet.get('authorDisplayName') or ''}: {safe_reply}",
            )
        else:
            if auto_reply:
                if not recent_for_auto:
                    stats["skipped_old"] += 1
                elif not decision.auto_allowed or decision.category not in SAFE_AUTO_CATEGORIES:
                    stats["skipped_review"] += 1
                elif auto_count >= max_auto_replies or stats["auto_replied"] >= max_auto_replies_per_scan:
                    stats["skipped_limit"] += 1
                elif int(budget["spendable"]) < COMMENT_REPLY_COST:
                    stats["quota_blocked"] += 1
            stats["queued"] += 1

    set_setting(
        conn,
        f"comment_scan_watermark_{profile}",
        (now - timedelta(minutes=2)).isoformat(),
    )
    log_action(
        conn,
        profile=profile,
        category="коментарі",
        action="Сканування",
        details=(
            f"нових {stats['seen']}, авто {stats['auto_replied']}, "
            f"API читань {stats['api_reads']}, відомих {stats['known_skipped']}, "
            f"на перевірку {stats['skipped_review']}, "
            f"застарілих {stats['skipped_old']}, "
            f"ліміт {stats['skipped_limit']}, "
            f"квота {stats['quota_blocked']}"
        ),
    )
    return stats


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
    profile_name = getattr(client, "profile", None)
    auto_count = today_auto_reply_count(conn, profile_name)

    if quota_exhausted(conn):
        stats["quota_blocked"] += 1
        return stats

    profile_name = getattr(client, "profile", "default")
    channel_key = f"youtube_channel_id_{profile_name}"
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
                    f"reply_template_{profile_name}_{decision.category}",
                    get_setting(
                        conn,
                        f"reply_template_{decision.category}",
                        DEFAULT_REPLY_TEMPLATES[decision.category],
                    ),
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
                _record_reply(conn, auto=True, profile=profile_name)
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

def reply_one_queued_safe_comment(
    client: YouTubeClient,
    conn: sqlite3.Connection,
    profile: str,
    *,
    max_auto_age_hours: int = DEFAULT_AUTO_REPLY_MAX_AGE_HOURS,
    max_auto_replies: int = DEFAULT_MAX_AUTO_REPLIES_PER_DAY,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "sent": 0,
        "quota_blocked": 0,
        "limit_blocked": 0,
        "comment_id": "",
        "category": "",
        "author": "",
    }

    if quota_exhausted(conn):
        result["quota_blocked"] = 1
        return result
    if today_auto_reply_count(conn, profile) >= max_auto_replies:
        result["limit_blocked"] = 1
        return result

    budget = quota_budget_status(conn)
    if int(budget["spendable"]) < COMMENT_REPLY_COST:
        result["quota_blocked"] = 1
        return result

    rows = conn.execute(
        """SELECT c.comment_id,c.author,c.published_at,c.category,c.reply_text
           FROM comments c
           JOIN videos v ON v.video_id=c.video_id
           WHERE v.profile=?
             AND c.status='new'
             AND c.category IN ('thanks','links','donate','schedule')
           ORDER BY c.published_at DESC
           LIMIT 250""",
        (profile,),
    ).fetchall()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_auto_age_hours)
    for row in rows:
        raw_published = str(row["published_at"] or "")
        try:
            published = datetime.fromisoformat(raw_published.replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if published < cutoff:
            continue

        comment_id = str(row["comment_id"])
        category = str(row["category"] or "")
        reply_text = str(row["reply_text"] or "").strip()
        if not reply_text:
            reply_text = _reply_template_for(
                conn, profile, category, comment_id
            )
        safe_reply = _validated_reply_text(reply_text)

        try:
            client.reply(comment_id, safe_reply)
        except Exception as exc:
            if _is_quota_error(exc):
                mark_quota_exhausted(conn)
                result["quota_blocked"] = 1
                return result
            raise

        mark_replied(conn, comment_id, safe_reply)
        _record_reply(conn, auto=True, profile=profile)
        log_action(
            conn,
            profile=profile,
            category="коментарі",
            action="Тестова автовідповідь",
            details=f"{row['author'] or ''}: {safe_reply}",
        )
        result.update(
            {
                "sent": 1,
                "comment_id": comment_id,
                "category": category,
                "author": str(row["author"] or ""),
            }
        )
        return result

    return result


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
    profile = getattr(client, "profile", None)
    _record_reply(conn, auto=False, profile=profile)
    log_action(
        conn,
        profile=profile,
        category="коментарі",
        action="Ручна відповідь",
        details=f"{comment_id}: {safe_reply}",
    )