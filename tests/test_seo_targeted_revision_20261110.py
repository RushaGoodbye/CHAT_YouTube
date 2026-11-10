"""Regression for source-aware targeted editorial repairs, no LM Studio needed."""
import json

from rg_youtube_control import seo_editorial_reviewer as editor
from rg_youtube_control import seo_quality_gate


def test_critic_title_issue_repairs_ab_variants_without_clobbering_description(monkeypatch):
    draft = {
        "title": "Росіянин заявив, що хоче бачити Україну частиною РФ",
        "title_variants": [
            "Розмова про об'єднання територій",
            "Росіянин про війну",
            "Погляди співрозмовника",
        ],
        "description": "Перевірений опис. " * 25,
        "tags": ["мобілізація", "війна", "Росія", "Путін", "чат рулетка", "Україна", "політика", "розмова"],
    }
    patch = {
        "title_variants": [
            "Росіянин хоче, щоб Україна стала Росією",
            "Що росіянин говорить про війну?",
            "Його слова про Україну та Росію",
        ],
        # This unrelated replacement must not corrupt accepted fields.
        "description": "Непідтверджене твердження.",
    }
    monkeypatch.setattr(editor, "lm_studio_chat", lambda *_a, **_k: json.dumps(patch, ensure_ascii=False))
    monkeypatch.setattr(seo_quality_gate, "inspect_editorial_targets", lambda _p: {"editorial_gate_pass": True, "issues": {}})
    monkeypatch.setattr(editor, "review_seo_candidate", lambda **_k: {
        "review_status": "NEEDS_HUMAN_REVIEW", "issues": [], "publication_allowed": False,
    })
    result = editor.revise_seo_candidate(
        draft=draft,
        source_notes=[{"time": "00:00:01", "quote": "Я хочу, чтобы Украина стала Россией."}],
        first_review={"review_status": "NEEDS_REVISION", "issues": [{"field": "title", "reason": "A/B wording unsupported"}]},
    )
    assert result["revised"] is True
    assert result["candidate"]["title_variants"] == patch["title_variants"]
    assert result["candidate"]["description"] == draft["description"]
    assert result["candidate"]["tags"] == draft["tags"]
    assert result["publication_allowed"] is False


def test_unresolved_revision_reports_actual_second_review(monkeypatch):
    draft = {
        "title": "Початкова назва",
        "title_variants": ["Варіант А", "Варіант Б", "Варіант В"],
        "description": "Точний опис. " * 32,
        "tags": ["один", "два", "три", "чотири", "п'ять", "шість", "сім", "вісім"],
    }
    responses = iter([{"title": "Питання про війну"}, {"title": "Суперечка про війну"}])
    monkeypatch.setattr(editor, "lm_studio_chat", lambda *_a, **_k: json.dumps(next(responses), ensure_ascii=False))
    monkeypatch.setattr(seo_quality_gate, "inspect_editorial_targets", lambda _p: {"editorial_gate_pass": True, "issues": {}})
    monkeypatch.setattr(editor, "review_seo_candidate", lambda **_k: {
        "review_status": "NEEDS_REVISION", "issues": [{"field": "title", "reason": "still not grounded"}],
    })
    result = editor.revise_seo_candidate(
        draft=draft,
        source_notes=[{"time": "00:01:00", "quote": "Говорили про війну"}],
        first_review={"review_status": "NEEDS_REVISION", "issues": [{"field": "title", "reason": "original mismatch"}]},
    )
    assert result["revised"] is False
    assert result["revision_error"] == "INDEPENDENT_REVIEW_STILL_REJECTS"
    assert result["last_review"]["issues"][0]["reason"] == "still not grounded"
