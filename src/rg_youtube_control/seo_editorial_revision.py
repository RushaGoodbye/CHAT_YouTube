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
    prior_failure = ""
    for attempt in range(2):
        if attempt == 0:
            messages = [
                {"role": "system", "content": "Український редактор. Тільки JSON. Без вигадок."},
                {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
            ]
        else:
            # Repair the format or remove unsupported numeric details. Never
            # change the source text and never accept the earlier bad draft.
            # Start clean rather than repeating the rejected topic, summary
            # or critic assertions. They can anchor the LLM to a false claim.
            location = context.casefold().find(quote.casefold())
            if location >= 0:
                local_context = context[
                    max(0, location - 350):location + len(quote) + 350
                ]
            else:
                local_context = quote
            repair_request = {
                "original_quote": quote,
                "local_context": local_context,
                "previous_error": prior_failure,
                "task": (
                    "Стисло опиши українською, про що йдеться у репліці. "
                    "Збережи питання як питання, не стверджуй правдивість сказаного. "
                    "Поверни тільки JSON з topic (5-110 символів) та "
                    "summary_uk (15-350 символів). Якщо немає підтвердження "
                    "місця, числа або причин у контексті, не додавай їх. "
                    "Не додавай нових чисел або фактів."
                ),
            }
            messages = [
                {"role": "system", "content": "Виправ JSON та необґрунтовані числа. Тільки JSON."},
                {"role": "user", "content": json.dumps(repair_request, ensure_ascii=False)},
            ]
        try:
            raw = chat(
                messages, model=model, timeout=timeout,
                temperature=0, json_mode=True,
            )
            answer = json.loads(str(raw).strip())
            if not isinstance(answer, dict):
                raise ValueError("NOT_OBJECT")
            topic = _compact(answer.get("topic"))
            summary = _compact(answer.get("summary_uk"))
            if not (5 <= len(topic) <= 110 and 15 <= len(summary) <= 350):
                raise ValueError("INVALID_REPAIR_LENGTH")
            from .seo_editorial_triage import vague_topic_warning
            if vague_topic_warning(topic):
                prior_failure = "VAGUE_TOPIC: no concrete referent, action or event"
                if attempt == 1:
                    return {
                        "status": "BLOCKED_VAGUE_TOPIC",
                        "attempts": 2,
                        "proposal": None,
                        "editorial_approved": False,
                        "publication_allowed": False,
                    }
                continue
            from .seo_spoken_numbers import grounded_number_values
            context_numbers = grounded_number_values(context)
            new_numbers = sorted(
                set(re.findall(r"(?<!\w)\d+(?!\w)", topic + " " + summary))
                - context_numbers
            )
            if new_numbers:
                prior_failure = "UNSUPPORTED_NUMBERS: " + ", ".join(new_numbers)
                if attempt == 1:
                    return {
                        "status": "BLOCKED_UNSUPPORTED_NUMBER",
                        "unsupported_numbers": new_numbers,
                        "attempts": 2,
                        "proposal": None,
                        "editorial_approved": False,
                        "publication_allowed": False,
                    }
                continue
            return {
                "status": "REVIEW_REQUIRED",
                "proposal": {"topic": topic, "summary_uk": summary},
                "verbatim_quote_unchanged": quote,
                "attempts": attempt + 1,
                "editorial_approved": False,
                "publication_allowed": False,
            }
        except (ValueError, TypeError, KeyError, RuntimeError, TimeoutError, OSError):
            prior_failure = "INVALID_JSON_OR_CONTENT"
            continue
    return {
        "status": "BLOCKED_REPAIR_FAILURE",
        "attempts": 2,
        "proposal": None,
        "editorial_approved": False,
        "publication_allowed": False,
    }
