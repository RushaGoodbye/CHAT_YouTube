"""Second-pass local editorial critic. Review-only, never publication authority."""
from __future__ import annotations

import json
from typing import Any

from .lm_studio_client import lm_studio_chat


def review_seo_candidate(
    *,
    draft: dict[str, Any],
    source_notes: list[dict[str, Any]],
    model: str = "",
) -> dict[str, Any]:
    """Review claims against timestamped source notes with a separate model call.

    The model is explicitly not permitted to approve YouTube publication.
    Missing or invalid reviewer results fail closed.
    """
    prompt = (
        "Ти НЕЗАЛЕЖНИЙ критичний редактор українського YouTube SEO. "
        "Звір кожен заголовок, кожну тезу опису й теги ТІЛЬКИ з цитатами "
        "у source_notes. Не використовуй знання поза джерелом. "
        "Шукай: вигадані факти, невірний вибір головної теми, "
        "русизми, загальні назви, рекламні перебільшення, "
        "непідтверджені твердження, нецільові теги. "
        "Відповідай JSON з ключами verdict ('revise' або 'review'), "
        "issues (масив об'єктів {field,reason,evidence}), "
        "recommended_changes (масив коротких пропозицій). "
        "Ніколи не повертай 'approved' або дозвіл на публікацію. "
        "Кандидат: " + json.dumps(draft, ensure_ascii=False) +
        "\nЦитати: " + json.dumps(source_notes, ensure_ascii=False)
    )
    try:
        raw = lm_studio_chat(
            [{"role": "system", "content": "Суворий незалежний редактор. Лише JSON."},
             {"role": "user", "content": prompt}],
            model=model, json_mode=True, max_tokens=2600,
            reasoning_effort="none", timeout=180,
        )
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("invalid reviewer object")
        issues = value.get("issues")
        if not isinstance(issues, list):
            raise ValueError("missing issues")
        return {
            "review_status": "NEEDS_REVISION" if issues or value.get("verdict") == "revise" else "NEEDS_HUMAN_REVIEW",
            "issues": issues,
            "recommended_changes": value.get("recommended_changes") if isinstance(value.get("recommended_changes"), (list, dict)) else [],
            "editorial_approved": False,
            "publication_allowed": False,
        }
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        return {
            "review_status": "REVIEWER_FAILED",
            "issues": [{"field": "reviewer", "reason": type(exc).__name__, "evidence": ""}],
            "recommended_changes": [],
            "editorial_approved": False,
            "publication_allowed": False,
        }
