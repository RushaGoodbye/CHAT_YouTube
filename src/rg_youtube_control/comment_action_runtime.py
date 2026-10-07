from __future__ import annotations

import sqlite3

from .config import SAFE_AUTO_CATEGORIES
from .db import save_comment_draft
from .service import _reply_template_for


def prepare_action_reply_drafts(
    conn: sqlite3.Connection,
    profile: str,
    *,
    limit: int = 20,
) -> dict[str, int]:
    rows = conn.execute(
        """SELECT c.comment_id,c.author,c.category,c.action
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
