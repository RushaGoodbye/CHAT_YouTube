"""Conservative guard for unattended YouTube replies.

Pure checks are separated from the YouTube client for offline testing.
No switch is enabled by importing this module.
"""
from __future__ import annotations

import re

# Only short, unmistakable social acknowledgements or stable official links.
UNATTENDED_CATEGORIES = frozenset({"thanks", "support", "greeting", "wishes"})
RISKY_TEXT = re.compile(
    r"(?i)(?:https?://|www\.|@\w+|"
    r"\b(?:війна|война|зсу|всу|збір|сбор|донат|переказ|перевод|"
    r"лікування|лечение|смерть|убийство|путін|путин|трамп|"
    r"росія|россия|україна|украина)\b|[?？])"
)


def unattended_reply_allowed(
    *, category: str, comment_text: str, reply_text: str,
    already_replied: bool = False, explicitly_enabled: bool = False,
) -> tuple[bool, str]:
    if not explicitly_enabled:
        return False, "autopilot_not_enabled"
    if already_replied:
        return False, "already_replied"
    if category not in UNATTENDED_CATEGORIES:
        return False, "category_requires_review"
    source = " ".join((comment_text or "").split())
    answer = " ".join((reply_text or "").split())
    if not source or not answer or len(source) > 160 or len(answer) > 280:
        return False, "content_length_or_empty"
    if RISKY_TEXT.search(source) or RISKY_TEXT.search(answer):
        return False, "sensitive_or_question"
    return True, "safe_acknowledgement"
