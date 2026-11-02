from __future__ import annotations

import sqlite3

from .config import SAFE_AUTO_CATEGORIES
from .db import save_comment_draft
from .service import _reply_template_for
from .comment_autopilot_guard import unattended_reply_allowed


def prepare_action_reply_drafts(
    conn: sqlite3.Connection,
    profile: str,
    *,
    limit: int = 20,
) -> dict[str, int]:
    rows = conn.execute(
        """SELECT c.comment_id,c.author,c.category,c.action,c.text
           FROM comments c
           JOIN videos v ON v.video_id=c.video_id
           WHERE v.profile=?
             AND c.status='new'
             AND c.action='reply'
             AND COALESCE(c.draft_state,'')=''
           ORDER BY c.published_at DESC
           LIMIT ?""",
        (profile, max(1, int(limit))),
    ).fetchall()

    ready = skipped = errors = 0
    for row in rows:
        comment_id = str(row["comment_id"])
        category = str(row["category"] or "")
        if category not in SAFE_AUTO_CATEGORIES:
            save_comment_draft(
                conn,
                comment_id,
                "",
                state="skipped",
                reason=f"action_reply_category_not_safe:{category}",
            )
            skipped += 1
            continue
        try:
            reply = _reply_template_for(
                conn,
                profile,
                category,
                comment_id,
                str(row["author"] or ""),
            )
            allowed, reason = unattended_reply_allowed(
                category=category,
                comment_text=str(row["text"] or ""),
                reply_text=reply,
                explicitly_enabled=True,
            )
            if not allowed:
                save_comment_draft(conn, comment_id, "", state="skipped", reason=f"needs_human_review:{reason}")
                skipped += 1
                continue
            if save_comment_draft(
                conn,
                comment_id,
                reply,
                state="ready",
                reason=f"action_safe_template:{category}",
            ):
                ready += 1
        except Exception as exc:
            save_comment_draft(
                conn,
                comment_id,
                "",
                state="error",
                reason=f"action_reply_error:{str(exc)[:300]}",
            )
            errors += 1

    return {
        "processed": len(rows),
        "ready": ready,
        "skipped": skipped,
        "errors": errors,
    }


def preview_safe_auto_replies(
    conn: sqlite3.Connection,
    profile: str,
    *,
    limit: int = 100,
) -> dict[str, int]:
    """Read-only preflight. Never contacts YouTube or changes saved comments."""
    from .comment_autopilot_guard import unattended_reply_allowed
    rows = conn.execute(
        """SELECT c.comment_id,c.text,c.category,c.reply_text,c.status
           FROM comments c JOIN videos v ON v.video_id=c.video_id
           WHERE v.profile=? AND c.status='new'
           ORDER BY c.published_at DESC LIMIT ?""",
        (profile, max(1, min(int(limit), 500))),
    ).fetchall()
    result = {"checked": len(rows), "eligible": 0, "manual_review": 0, "no_reply": 0}
    for row in rows:
        reply = str(row["reply_text"] or "").strip()
        if not reply:
            result["no_reply"] += 1
            continue
        eligible, _reason = unattended_reply_allowed(
            category=str(row["category"] or ""),
            comment_text=str(row["text"] or ""),
            reply_text=reply,
            explicitly_enabled=True,
        )
        result["eligible" if eligible else "manual_review"] += 1
    return result


def propose_diverse_safe_replies(
    conn: sqlite3.Connection, profile: str, *, limit: int = 100,
) -> dict:
    """Preview diverse reply texts without DB writes or YouTube calls."""
    from hashlib import sha256
    templates = {
        "thanks": ("Дякуємо, що підтримуєте канал!", "Щиро вдячні за ваші слова!", "Ваша підтримка дуже цінна для нас."),
        "support": ("Дякуємо за підтримку!", "Цінуємо, що ви з нами!", "Дякуємо за добрі слова та підтримку!"),
        "greeting": ("Вітаємо! Раді бачити вас на каналі.", "Привіт! Дякуємо, що завітали.", "Вітаємо і дякуємо за увагу до каналу!"),
        "wishes": ("Щиро дякуємо за побажання!", "Дякуємо за теплі слова!", "Навзаєм! Дякуємо за добрі побажання."),
    }
    rows = conn.execute(
        """SELECT c.comment_id,c.text,c.category FROM comments c
           JOIN videos v ON v.video_id=c.video_id
           WHERE v.profile=? AND c.status='new' AND c.action='reply'
           ORDER BY c.published_at DESC LIMIT ?""",
        (profile, max(1, min(int(limit), 500))),
    ).fetchall()
    proposals = []
    withheld = 0
    for row in rows:
        cat = str(row["category"] or "")
        if cat not in templates:
            withheld += 1
            continue
        cid = str(row["comment_id"])
        choices = templates[cat]
        index = int.from_bytes(sha256(cid.encode("utf-8")).digest()[:4], "big") % len(choices)
        answer = choices[index]
        allowed, _reason = unattended_reply_allowed(
            category=cat, comment_text=str(row["text"] or ""),
            reply_text=answer, explicitly_enabled=True,
        )
        if allowed:
            proposals.append({"comment_id": cid, "category": cat, "reply": answer})
        else:
            withheld += 1
    return {"checked": len(rows), "proposed": len(proposals),
            "withheld": withheld, "distinct_replies": len({x["reply"] for x in proposals}),
            "proposals": proposals, "published": 0}
