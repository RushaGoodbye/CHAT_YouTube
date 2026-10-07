from __future__ import annotations

import json
import re
import sqlite3

from .db import save_comment_action
from .free_tools import DEFAULT_OLLAMA_MODEL, ollama_chat


def _json_object(text: str) -> dict:
    value = str(text or "").strip()
    if value.startswith("\`\`\`"):
        value = re.sub(r"^\s*\`\`\`(?:json)?\s*", "", value, flags=re.I)
        value = re.sub(r"\s*\`\`\`\s*$", "", value)
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Ollama не повернула JSON.")
        payload = json.loads(value[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Очікувався JSON-об'єкт.")
    return payload


def semantic_action_candidate(
    comment_text: str,
    *,
    model: str = DEFAULT_OLLAMA_MODEL,
) -> dict[str, str]:
    source = " ".join(str(comment_text or "").split()).strip()
    if not source:
        return {"action": "skip", "reason": "empty_comment", "category": "empty"}

    if "?" in source:
        return {
            "action": "review",
            "reason": "explicit_question_requires_review",
            "category": "question",
        }

    prompt = f"""
Класифікуй один YouTube-коментар для каналу «РАША ГУДБАЙ».
Це НЕ генерація відповіді. Нічого не публікуй.

Обери рівно одну дію:
- like: доброзичливий, позитивний, підтримуючий, схвальний, дотепний або
  конструктивний коментар, де лайк доречний і окрема відповідь не потрібна;
- skip: образа, токсичність, спам, беззмістовний текст, повторюваний лозунг,
  провокація або коментар, на який краще не реагувати;
- review: неоднозначний, політичний/спірний, фактичне твердження, яке потребує
  перевірки, або будь-який випадок, де ти не впевнений.

Консервативне правило:
- якщо сумніваєшся між like і review - review;
- не оцінюй істинність політичних або фактичних тверджень;
- не вигадуй контекст;
- не перетворюй review на like лише через позитивний тон, якщо зміст спірний.

Поверни ТІЛЬКИ JSON:
{{"action":"like|skip|review","reason":"коротка причина","category":"коротка категорія"}}

КОМЕНТАР:
{source}
""".strip()

    try:
        raw = ollama_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Ти консервативний модератор YouTube-коментарів. "
                        "Ти лише класифікуєш дію, не пишеш відповідей."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            model=model,
            temperature=0.05,
            json_mode=True,
        )
        payload = _json_object(raw)
    except Exception as exc:
        return {
            "action": "review",
            "reason": f"ollama_error:{str(exc)[:160]}",
            "category": "semantic_error",
        }

    action = str(payload.get("action") or "").strip().casefold()
    if action not in {"like", "skip", "review"}:
        action = "review"
    reason = str(payload.get("reason") or "").strip()[:240] or "semantic_review"
    category = str(payload.get("category") or "").strip()[:80] or "semantic_review"
    return {"action": action, "reason": reason, "category": category}


def review_comment_actions_local(
    conn: sqlite3.Connection,
    profile: str,
    *,
    limit: int = 20,
    model: str = DEFAULT_OLLAMA_MODEL,
) -> dict[str, int]:
    rows = conn.execute(
        """SELECT c.comment_id,c.text
           FROM comments c
           JOIN videos v ON v.video_id=c.video_id
           WHERE v.profile=?
             AND c.status='new'
             AND c.action='review'
             AND COALESCE(c.action_reason,'')='semantic_second_stage'
           ORDER BY c.published_at DESC
           LIMIT ?""",
        (profile, max(1, int(limit))),
    ).fetchall()

    counts = {"processed": 0, "like": 0, "review": 0, "skip": 0, "errors": 0}
    for row in rows:
        result = semantic_action_candidate(
            str(row["text"] or ""),
            model=model,
        )
        action = str(result.get("action") or "review")
        reason = str(result.get("reason") or "semantic_review")
        category = str(result.get("category") or "semantic_review")
        if reason.startswith("ollama_error:"):
            counts["errors"] += 1
        if save_comment_action(
            conn,
            str(row["comment_id"]),
            action=action,
            reason=f"semantic:{reason}",
            category=category,
        ):
            counts["processed"] += 1
            counts[action] = counts.get(action, 0) + 1
    return counts
