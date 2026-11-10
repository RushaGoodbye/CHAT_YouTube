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



def select_independent_source_notes(
    evidence_report: dict[str, Any], *, max_blocks: int = 24, max_notes: int = 40
) -> list[dict[str, str]]:
    """Sample literal evidence across the recording, then secondary topics.

    The first pass represents the beginning, middle and end. The second pass
    covers independent subjects without crowding out late-source quotations.
    """
    blocks = [
        block for block in (evidence_report.get("blocks") or [])
        if isinstance(block, dict) and block.get("verified") is not False
        and any(
            isinstance(topic, dict) and str(topic.get("evidence") or "").strip()
            for topic in (block.get("topics") or [])
        )
    ]
    if not blocks or max_blocks < 1 or max_notes < 1:
        return []
    take = min(max_blocks, len(blocks))
    positions = (
        [0] if take == 1
        else sorted({
            round(i * (len(blocks) - 1) / (take - 1))
            for i in range(take)
        })
    )
    selected = [blocks[i] for i in positions]
    notes: list[dict[str, str]] = []
    for tier in range(3):
        for block in selected:
            topics = [
                topic for topic in block.get("topics") or []
                if isinstance(topic, dict) and str(topic.get("evidence") or "").strip()
            ]
            if tier >= len(topics):
                continue
            topic = topics[tier]
            notes.append({
                "time": str(
                    block.get("start_stamp")
                    or block.get("start")
                    or block.get("start_s")
                    or ""
                ),
                "topic": str(topic.get("topic") or "")[:140],
                "quote": str(topic.get("evidence") or "")[:350],
            })
            if len(notes) >= max_notes:
                return notes
    return notes


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
        "Це чат-рулетка з РІЗНИМИ мовцями: протилежні позиції "
        "двох людей не спростовують одна одну. Якщо хоча б одна "
        "точна цитата підтверджує, що людина висловила позицію, "
        "не називай її непідтвердженою лише через іншу цитату. "
        "Водночас не перетворюй позицію учасника на встановлений факт. "
        "Не вигадуй додатковий зміст, мотив чи нібито спростування. "
        "Шукай: вигадані факти, невірний вибір головної теми, "
        "русизми, загальні назви, рекламні перебільшення, "
        "непідтверджені твердження, нецільові теги. "
        "КРИТИЧНО: відокремлюй ПОВІДОМЛЕННЯ ПРО ПОЗИЦІЮ від "
        "твердження редакції про дійсність: 'співрозмовник заперечує війну' "
        "означає, що людина це сказала, а НЕ те, що війни немає. "
        "Тег 'війна в Україні' доречний, коли люди прямо обговорюють "
        "війну, навіть якщо одна сторона її заперечує. "
        "Не звинувачуй опис у вигадці, якщо він коректно приписує "
        "думку учаснику. Теги можуть описувати конкретні ДРУГОРЯДНІ "
        "епізоди, не лише найчастішу тему. Не відхиляй буквальний "
        "підтверджений тег лише через коротку тривалість епізоду. "
        "Запитання про дітей і алкоголь допустиме як A/B ракурс, "
        "якщо обидва прямо звучать у тому самому уривку; "
        "це не доказ, що питання є головною темою відео. "
        "Водночас перевіряй наявність КОНКРЕТНИХ "
        "цитат і не пропускай вигаданий наслідок, мотив або число. "
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
        verdict = str(value.get("verdict") or "").strip().casefold()
        # The old branch treated ANY non-"revise" value (including missing,
        # malformed, or forbidden "approved") as successful independent QA.
        # Demand the exact two-value schema and block inconsistent decisions.
        if verdict not in {"review", "revise"}:
            raise ValueError("invalid independent reviewer verdict")
        if verdict == "review" and issues:
            verdict = "revise"
        if value.get("reviewer_language_warning"):
            verdict = "revise"
            issues.append({
                "field": "reviewer_language",
                "reason": "REVIEWER_NON_UKRAINIAN_OUTPUT",
                "evidence": "",
            })
        return {
            "review_status": "NEEDS_REVISION" if verdict == "revise" else "NEEDS_HUMAN_REVIEW",
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
    """Bounded two-stage source-aware revision, never publication authority."""
    if first_review.get("review_status") != "NEEDS_REVISION" or not source_notes:
        return {
            "candidate": draft, "review": first_review, "revised": False,
            "editorial_approved": False, "publication_allowed": False,
        }
    from .seo_quality_gate import inspect_editorial_targets
    working = draft
    critique = first_review
    required_fields = ("title", "description", "title_variants", "tags")
    complete_draft = all(draft.get(field) for field in required_fields)
    failure_code = "NO_VALID_REVISION"
    for attempt in range(2):
        instruction = (
            "Ти редактор SEO для українського каналу. Зроби АДРЕСНЕ "
            "виправлення чернетки за конкретними помилками редактора. "
            "Збережи всі підтверджені цитатами формулювання та правильні "
            "поля. Не переписуй безпомилкові фрази заради стилю. "
            "Поверни ПОВНИЙ пакет JSON з title, title_variants "
            "(РІВНО 3 змістовні, різні), "
            "description (400-900 символів), tags (8-12 природних "
            "українських конкретних пошукових фраз). "
            "Виправ УСІ попередні зауваження. Якщо оригінальний пакет "
            "повний, поверни ЛИШЕ поля з переліку помилок, не дублюй "
            "поля без зауважень. Інакше поверни повний пакет. "
            "Жодних шаблонних A/B "
            "або штучних сполучень різних сюжетів. "
            "Твердження, причини, результати й числа мають бути "
            "прямо засвідчені дослівними репліками. "
            "Фраза 'співрозмовник стверджує' описує його позицію, "
            "а не підтверджує її як факт. "
            "Не додавай 'загиблих', 'викриття фейків' чи інших "
            "подій, якщо саме таких тверджень немає в цитатах. "
            "ЗАБОРОНЕНО підміняти 'сказав' словами 'визнав', "
            "'довів', 'викрив', 'спростував', якщо це лише репліка. "
            "Не підміняй 'підтримує Путіна' на 'голосування за Путіна'. "
            "Не перетворюй запитання чи думку на факт, причину або висновок. "
            "Кожен тег має відповідати саме сказаному, без домислів. "
            "Теги не можуть бути неграмотними або повторювати "
            "одну пошукову фразу іншою формою. "
            "Для кожної виправленої фрази звір зміст із ЦИТАТОЮ, "
            "але не додавай пояснень чи цитат поза JSON. "
            "Не включай review_status чи publication_allowed. "
            "ЧЕРНЕТКА: " + json.dumps(working, ensure_ascii=False) +
            "\nКОНКРЕТНІ ПОМИЛКИ: " + json.dumps(
                critique.get("issues", []), ensure_ascii=False
            ) +
            "\nЦИТАТИ З ЧАСОМ: " + json.dumps(
                source_notes, ensure_ascii=False
            )
        )
        try:
            raw = lm_studio_chat(
                [
                    {"role": "system", "content": (
                        "Український SEO-редактор. Лише JSON. "
                        "Дослівні цитати єдине джерело фактів."
                    )},
                    {"role": "user", "content": instruction},
                ],
                model=model, json_mode=True, max_tokens=2500,
                reasoning_effort="none", timeout=180,
            )
            patch = json.loads(raw)
            if not isinstance(patch, dict):
                failure_code = "INVALID_JSON_OBJECT"
                continue
            # A valid full draft should not be destroyed by rewriting fields
            # that the independent critic did not reject. The model returns
            # only corrections for flagged fields; validate the merged package.
            allowed = set(required_fields)
            if complete_draft:
                flagged = {
                    str(issue.get("field") or "").strip()
                    for issue in critique.get("issues", [])
                    if isinstance(issue, dict)
                }
                flagged &= allowed
                if flagged:
                    allowed = flagged
            candidate = {**working, **{
                field: value for field, value in patch.items()
                if field in allowed and value
            }}
            if not all(candidate.get(key) for key in required_fields):
                failure_code = "INCOMPLETE_REVISION"
                continue
            gate = inspect_editorial_targets(candidate)
            if not gate.get("editorial_gate_pass"):
                failure_code = "EDITORIAL_FORMAT_UNRESOLVED"
                working = candidate
                critique = {
                    "issues": [
                        {"field": field, "reason": ",".join(reasons)}
                        for field, reasons in gate.get("issues", {}).items()
                    ]
                }
                continue
            if all(candidate.get(field) == working.get(field) for field in required_fields):
                failure_code = "UNCHANGED_REVISION"
                continue
            second_review = review_seo_candidate(
                draft=candidate, source_notes=source_notes, model=model,
            )
            if second_review.get("review_status") == "NEEDS_HUMAN_REVIEW":
                return {
                    "candidate": candidate, "review": second_review,
                    "format_and_editorial_gate": gate,
                    "revised": True,
                    "revision_attempts": attempt + 1,
                    "editorial_approved": False,
                    "publication_allowed": False,
                }
            working = candidate
            critique = second_review
            failure_code = "INDEPENDENT_REVIEW_STILL_REJECTS"
        except (RuntimeError, ValueError, TypeError, KeyError) as exc:
            failure_code = type(exc).__name__
            break
    return {
        "candidate": draft, "review": first_review,
        "revision_error": failure_code,
        "revised": False, "revision_attempts": 2,
        "editorial_approved": False,
        "publication_allowed": False,
    }
