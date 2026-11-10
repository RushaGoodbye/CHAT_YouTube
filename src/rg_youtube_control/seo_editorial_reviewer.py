"""Second-pass local editorial critic. Review-only, never publication authority."""
from __future__ import annotations

import json
from typing import Any

from .lm_studio_client import lm_studio_chat


def _normalized_issues(raw: Any) -> list[dict[str, str]]:
    """Normalize reviewer list/dict output; reject unrecognized shapes."""
    if isinstance(raw, list):
        return [item if isinstance(item, dict) else {"reason": str(item)} for item in raw if item]
    if isinstance(raw, dict):
        result = []
        for category, items in raw.items():
            for item in items if isinstance(items, list) else [items]:
                if item:
                    result.append({"field": str(category), "reason": str(item)})
        return result
    raise ValueError("invalid reviewer issues format")


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
        # Reviewer prose and suggestions are untrusted and must not be
        # interpreted as editorial approval or applied as metadata.
        from .seo_quality_gate import language_error
        suggestions = value.get("recommended_changes")
        suggestion_text = json.dumps(suggestions, ensure_ascii=False) if suggestions is not None else ""
        if language_error(suggestion_text):
            value["reviewer_language_warning"] = True
        issues = _normalized_issues(issues)
        return {
            "review_status": "NEEDS_REVISION" if issues or value.get("verdict") == "revise" else "NEEDS_HUMAN_REVIEW",
            "issues": issues,
            "reviewer_language_warning": bool(value.get("reviewer_language_warning")),
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


def revise_seo_candidate(
    *,
    draft: dict[str, Any],
    source_notes: list[dict[str, Any]],
    first_review: dict[str, Any],
    model: str = "",
) -> dict[str, Any]:
    """One bounded revision, then a fresh independent review. Never publish."""
    if first_review.get("review_status") != "NEEDS_REVISION" or not source_notes:
        return {"candidate": draft, "review": first_review, "revised": False,
                "editorial_approved": False, "publication_allowed": False}
    instruction = (
        "Ти редактор SEO для українського каналу. Перепиши ВЕСЬ пакет JSON "
        "із title, title_variants (рівно 3), description (від 400 символів), "
        "tags (8-12). Усунь кожне зауваження. Не вигадуй факти. "
        "Покладайся ЛИШЕ на цитати. Пиши нормативною українською, "
        "конкретно, без абстрактних назв чи шаблонних фраз. "
        "Не включай слова review_status чи publication_allowed. "
        "Чернетка: " + json.dumps(draft, ensure_ascii=False) +
        "\nЗауваження: " + json.dumps(first_review.get("issues", []), ensure_ascii=False) +
        "\nДжерела: " + json.dumps(source_notes, ensure_ascii=False)
    )
    try:
        raw = lm_studio_chat(
            [{"role": "system", "content": "SEO-редактор. Лише JSON."},
             {"role": "user", "content": instruction}],
            model=model, json_mode=True, max_tokens=2500,
            reasoning_effort="none", timeout=180,
        )
        candidate = json.loads(raw)
        if not isinstance(candidate, dict):
            raise ValueError("invalid revised candidate")
        required = ("title", "description", "title_variants", "tags")
        if not all(candidate.get(key) for key in required):
            raise ValueError("incomplete revised candidate")
        from .seo_quality_gate import inspect_editorial_targets
        gate = inspect_editorial_targets(candidate)
        # A rewrite that fails the same structural/editorial gate is not a
        # successful revision, even if the model produced valid JSON.
        if not gate.get("editorial_gate_pass"):
            raise ValueError("revised seo failed editorial gate")
        if (candidate.get("title") == draft.get("title")
                and candidate.get("description") == draft.get("description")):
            raise ValueError("unchanged seo after revision")
        second_review = review_seo_candidate(
            draft=candidate, source_notes=source_notes, model=model,
        )
        # Only a revision with no remaining model-identified defects is
        # eligible for human review. This is never publication approval.
        if second_review.get("review_status") != "NEEDS_HUMAN_REVIEW":
            raise ValueError("revised seo still requires correction")
        # A model passing its own structural tests is never human approval.
        return {
            "candidate": candidate,
            "review": second_review,
            "format_and_editorial_gate": gate,
            "revised": True,
            "editorial_approved": False,
            "publication_allowed": False,
        }
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        return {
            "candidate": draft, "review": first_review,
            "revision_error": type(exc).__name__, "revised": False,
            "editorial_approved": False, "publication_allowed": False,
        }
