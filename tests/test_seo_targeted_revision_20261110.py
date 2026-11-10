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


def test_revision_checks_ab_against_full_evidence_before_critic(monkeypatch):
    from rg_youtube_control import dialogue_seo
    draft = {
        "title": "Назва про мобілізацію",
        "title_variants": ["Розмова про мобілізацію", "Питання про війну в Росії", "Думка про Україну"],
        "description": "Точний опис. " * 35,
        "tags": ["мобілізація", "війна", "Росія", "Україна", "Путін", "реакція", "розмова", "чат рулетка"],
    }
    count = {"reviews": 0}
    def reviewer_stub(**_k):
        count["reviews"] += 1
        return {"review_status": "NEEDS_HUMAN_REVIEW", "issues": []}
    monkeypatch.setattr(editor, "review_seo_candidate", reviewer_stub)
    monkeypatch.setattr(editor, "lm_studio_chat", lambda *_a, **_k: json.dumps({"title_variants": [
        "Мобілізація і питання про війну", "Росіянин про українців та війну", "Що сказали про Україну?",
    ]}, ensure_ascii=False))
    monkeypatch.setattr(seo_quality_gate, "inspect_editorial_targets", lambda _p: {"editorial_gate_pass": True, "issues": {}})
    monkeypatch.setattr(dialogue_seo, "ab_title_issues", lambda *_a, **_k: ["not supported by source"])
    result = editor.revise_seo_candidate(
        draft=draft,
        source_notes=[{"time": "00:00:10", "quote": "Була мобілізація"}],
        first_review={"review_status": "NEEDS_REVISION", "issues": [{"field": "title", "reason": "incorrect AB"}]},
        evidence_report={"blocks": []},
    )
    assert result["revised"] is False
    assert count["reviews"] == 0
    assert result["revision_error"] in {"AB_EVIDENCE_UNRESOLVED", "UNCHANGED_REVISION"}
    assert result["publication_allowed"] is False


def test_revision_rejects_number_not_in_original_caption(monkeypatch):
    draft = {
        "title": "Розмова про війну",
        "title_variants": ["Що кажуть про війну?", "Позиція щодо війни", "Війна та розмова"],
        "description": "Розмова про позиції людей. " * 18,
        "tags": ["раша гудбай", "чат рулетка", "війна", "росіяни", "Україна", "Росія", "мобілізація", "думки людей"],
    }
    monkeypatch.setattr(editor, "lm_studio_chat", lambda *_a, **_k: json.dumps({
        "title": "Втрати 9999 людей у війні",
    }, ensure_ascii=False))
    monkeypatch.setattr(seo_quality_gate, "inspect_editorial_targets", lambda _p: {"editorial_gate_pass": True, "issues": {}})
    monkeypatch.setattr(seo_quality_gate, "inspect_package", lambda _p: {"format_pass": True, "problems": []})
    result = editor.revise_seo_candidate(
        draft=draft,
        source_notes=[{"quote": "У нас війна"}],
        source_rows=[{"text": "Війна триває"}],
        first_review={"review_status": "NEEDS_REVISION", "issues": [{"field": "title", "reason": "wrong title"}]},
    )
    assert result["revised"] is False
    assert result["revision_error"] in {"NUMERIC_CLAIM_UNSUPPORTED", "UNCHANGED_REVISION"}
    assert result["publication_allowed"] is False


def test_format_failure_targets_only_bad_tags_on_next_revision(monkeypatch):
    draft = {
        "title": "Росіянин говорить про війну",
        "title_variants": [
            "Розмова про мобілізацію", "Питання про війну в Росії", "Слова про Україну",
        ],
        "description": "Учасники обговорюють свої позиції. " * 14,
        "tags": ["Раша Гудбай", "чат рулетка", "війна", "Росія", "Україна", "Путін", "мобілізація", "політика"],
    }
    calls = iter([
        {"tags": ["війна"]},
        {"tags": ["Раша Гудбай", "чат рулетка", "війна", "Росія", "Україна", "Путін", "мобілізація", "політика"]},
    ])
    monkeypatch.setattr(editor, "lm_studio_chat", lambda *_a, **_k: json.dumps(next(calls), ensure_ascii=False))
    monkeypatch.setattr(seo_quality_gate, "inspect_editorial_targets", lambda _p: {"editorial_gate_pass": True, "issues": {}})
    monkeypatch.setattr(editor, "review_seo_candidate", lambda **_k: {"review_status": "NEEDS_HUMAN_REVIEW", "issues": []})
    result = editor.revise_seo_candidate(
        draft=draft, source_notes=[{"quote": "Говоримо про війну"}],
        first_review={"review_status": "NEEDS_REVISION", "issues": [{"field": "tags", "reason": "weak tags"}]},
    )
    assert result["revised"] is True
    assert result["candidate"]["tags"] == draft["tags"]
    assert result["candidate"]["title"] == draft["title"]
    assert result["publication_allowed"] is False


def test_format_gate_reports_named_fields(monkeypatch):
    draft = {
        "title": "Тема про мобілізацію",
        "title_variants": ["Питання про війну", "Слова про Україну", "Суперечка про Росію"],
        "description": "Розмова з росіянином про війну. " * 15,
        "tags": ["Раша Гудбай", "чат рулетка", "війна", "Росія", "Україна", "Путін", "мобілізація", "політика"],
    }
    calls = []
    def fake_chat(messages, **kwargs):
        calls.append(messages[-1]["content"])
        return json.dumps({"tags": ["один"]}, ensure_ascii=False)
    monkeypatch.setattr(editor, "lm_studio_chat", fake_chat)
    monkeypatch.setattr(seo_quality_gate, "inspect_editorial_targets", lambda _p: {"editorial_gate_pass": True, "issues": {}})
    result = editor.revise_seo_candidate(
        draft=draft, source_notes=[{"quote": "Говоримо про війну"}],
        first_review={"review_status": "NEEDS_REVISION", "issues": [{"field": "tags", "reason": "weak tags"}]},
    )
    assert len(calls) == 2
    assert "FEWER_THAN_EIGHT" in calls[1]
    assert result["revised"] is False
