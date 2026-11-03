"""Source-constrained editorial repair for G2.

The repairer returns a review proposal, not a verified topic. The unchanged
original quote and the source context remain the authority. No auto-approval.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable


def _compact(text: Any) -> str:
    return " ".join(str(text or "").split())


def propose_editorial_revision(
    *, card: dict[str, Any], chat: Callable[..., str], model: str,
    timeout: float = 90.0,
) -> dict[str, Any]:
    quote = _compact(card.get("verbatim_quote"))
    context = _compact(card.get("source_context"))
    if len(quote) < 8 or quote.casefold() not in context.casefold():
        return {"status": "BLOCKED_SOURCE_CONTEXT", "proposal": None,
                "editorial_approved": False, "publication_allowed": False}
    request = {
        "original_quote": quote,
        "surrounding_transcript": context[:2500],
        "original_topic": card.get("proposed_topic", ""),
        "original_summary": card.get("proposed_summary", ""),
        "unverified_critic_objections": card.get("critic_issues_unverified", []),
        "requirements": [
            "Write only Ukrainian JSON fields topic and summary_uk.",
            "Report what the person says, never claim independent truth.",
            "Preserve whether something is a question, opinion, irony or allegation.",
            "Never introduce locations, names, numbers, dates or causes unless directly in source context.",
            "A critic can be wrong: resolve objections by re-reading the source, not obeying the critic.",
            "If no accurate standalone topic is possible, return empty topic and summary_uk.",
        ],
    }
    try:
        raw = chat(
            [{"role": "system", "content": "Український редактор. Тільки JSON. Без вигадок."},
             {"role": "user", "content": json.dumps(request, ensure_ascii=False)}],
            model=model, timeout=timeout, temperature=0, json_mode=True,
        )
        answer = json.loads(str(raw).strip())
        if not isinstance(answer, dict):
            raise ValueError("NOT_OBJECT")
        topic, summary = _compact(answer.get("topic")), _compact(answer.get("summary_uk"))
        if not (5 <= len(topic) <= 110 and 15 <= len(summary) <= 350):
            raise ValueError("INVALID_REPAIR_LENGTH")
        # Newly asserted numeric details are particularly high-risk. A
        # source context window must contain the exact digits before review.
        text = topic + " " + summary
        new_numbers = [x for x in re.findall(r"(?<!\w)\d+(?!\w)", text)
                       if x not in re.findall(r"(?<!\w)\d+(?!\w)", context)]
        if new_numbers:
            return {"status": "BLOCKED_UNSUPPORTED_NUMBER",
                    "unsupported_numbers": new_numbers, "proposal": None,
                    "editorial_approved": False, "publication_allowed": False}
        return {"status": "REVIEW_REQUIRED",
                "proposal": {"topic": topic, "summary_uk": summary},
                "verbatim_quote_unchanged": quote,
                "editorial_approved": False, "publication_allowed": False}
    except (ValueError, TypeError, KeyError, RuntimeError, TimeoutError, OSError):
        return {"status": "BLOCKED_REPAIR_FAILURE", "proposal": None,
                "editorial_approved": False, "publication_allowed": False}
