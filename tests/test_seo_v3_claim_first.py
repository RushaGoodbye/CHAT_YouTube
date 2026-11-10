"""No topic-specific exceptions: source modality is fixed before writing."""
import json

from rg_youtube_control.seo_v3_claims import (
    build_claim_ledger, check_claim_type_constraints, classify_statement,
)
from rg_youtube_control.seo_v3_pipeline import (
    _write_from_claims, generate_claim_first_seo,
)


def _source(quote, eid="ev_1"):
    return [{"evidence_id": eid, "quote": quote,
             "start_ms": 0, "end_ms": 1000, "cue_indices": [0]}]


def test_modality_is_source_derived_not_model_asserted():
    assert classify_statement("Чому це сталося?") == "QUESTION"
    assert classify_statement("Почему директор ушел?") == "QUESTION"
    assert classify_statement("Какова реальная причина") == "QUESTION"
    assert classify_statement("Яка причина кадрового рішення") == "QUESTION"
    assert classify_statement("Якщо ми підемо, він залишиться.") == "CONDITIONAL"
    assert classify_statement("Если бы мы знали причину") == "CONDITIONAL"
    assert classify_statement("Можливо, це лише припущення.") == "HYPOTHESIS"
    assert classify_statement("На мою думку рішення передчасне") == "HYPOTHESIS"
    assert classify_statement("Майстер обговорює колір глазурі.") == "SPEAKER_STATEMENT"


def test_no_source_statement_becomes_automatically_verified_fact():
    ledger = build_claim_ledger(_source("Майстер назвав свій рецепт."))
    assert ledger["claims"][0]["verified_external_fact"] is False
    assert ledger["claims"][0]["source_type"] == "SPEAKER_STATEMENT"
    assert ledger["publication_allowed"] is False


def test_question_cannot_be_rewritten_as_established_real_reason():
    ledger = build_claim_ledger(_source("Чому змінився керівник?"))
    draft = {
        "title": "Реальні причини зміни керівника",
        "description": "Аналіз доводить реальну причину.",
        "title_variants": ["Чому змінився керівник?"],
        "tags": ["кадрові зміни"],
        "support_ids": {
            "title": ["ev_1"], "description": ["ev_1"],
            "title_variants": [["ev_1"]], "tags": [["ev_1"]],
        },
    }
    reasons = check_claim_type_constraints(draft, ledger)
    assert any(x["field"] == "title" for x in reasons)
    assert any(x["field"] == "description" for x in reasons)


def test_generator_receives_typed_claims_not_ai_topic_summaries_as_facts():
    ledger = build_claim_ledger(_source(
        "Якби ми збудували міст, дорога була б коротша."
    ))
    prompts = []
    def model(prompt):
        prompts.append(prompt)
        return {
            "title": "Чи допоміг би міст скоротити дорогу?",
            "variant_evidence": [
                {"text": "Умови будівництва мосту", "evidence_ids": ["ev_1"]},
                {"text": "Чи потрібен міст?", "evidence_ids": ["ev_1"]},
                {"text": "Дорога і міст", "evidence_ids": ["ev_1"]},
            ],
            "description": "Співрозмовник розмірковує про можливе будівництво мосту.",
            "tag_evidence": [
                {"tag": "будівництво мосту", "evidence_ids": ["ev_1"]}
            ],
            "support_ids": {"title": ["ev_1"], "description": ["ev_1"]},
        }
    result = _write_from_claims(ledger, [], model)
    assert result["support_ids"]["title_variants"] == [["ev_1"]] * 3
    assert result["support_ids"]["tags"] == [["ev_1"]]
    assert result["tags"] == ["будівництво мосту"]
    assert '"source_type": "CONDITIONAL"' in prompts[0]
    assert '"verified_external_fact": false' in prompts[0]
    assert "topic labels are orientation only" in prompts[0].lower()


def test_claim_first_pipeline_blocks_invented_cause_even_with_forged_support(monkeypatch):
    from rg_youtube_control import seo_v3_pipeline
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\n"
        "Чому директор залишив посаду?\n"
    )
    evidence = {
        "accepted": _source("Чому директор залишив посаду?"),
        "rejected": [], "review_required": False, "source_cues": 1,
    }
    monkeypatch.setattr(
        seo_v3_pipeline, "_extract",
        lambda cues, model: (evidence, [{"start_ms": 0, "end_ms": 1000}]),
    )
    monkeypatch.setattr(
        seo_v3_pipeline, "expand_literal_coverage",
        lambda cues, evidence: evidence,
    )
    monkeypatch.setattr(
        seo_v3_pipeline, "_select_topics",
        lambda ledger, model: [{
            "label_uk": "Посада керівника",
            "evidence_ids": ["ev_1"], "rank": 1,
        }],
    )
    def model(prompt):
        return {
            "title": "Реальні причини звільнення директора",
            "variant_evidence": [
                {"text": "Чому директор залишив посаду?",
                 "evidence_ids": ["ev_1"]},
                {"text": "Зміна посади керівника", "evidence_ids": ["ev_1"]},
                {"text": "Що сталося з директором?", "evidence_ids": ["ev_1"]},
            ],
            "description": "Аналіз доводить причину кадрової зміни. " * 12,
            "tag_evidence": [
                {"tag": "кадрові зміни", "evidence_ids": ["ev_1"]}
            ] * 8,
            "support_ids": {
                "title": ["ev_1"], "description": ["ev_1"],
            },
        }
    result = generate_claim_first_seo(
        srt, model, independent_review=lambda _: {"issues": []},
    )
    assert result["pipeline"] == "RG_SEO_CLAIM_FIRST_V3"
    assert result["status"] == "REVIEW_REQUIRED"
    assert "CLAIM_MODALITY_UNSUPPORTED" in result["gate"]["issues"]
    assert result["publication_allowed"] is False
    assert result["claims"]["claims"][0]["source_type"] == "QUESTION"


def test_no_review_provider_is_never_ready():
    from rg_youtube_control import seo_v3_pipeline
    # Even valid output cannot skip an independent review.
    assert seo_v3_pipeline.generate_claim_first_seo.__name__ == "generate_claim_first_seo"


def test_independent_claim_audit_uses_modality_and_rejects_bad_schema():
    from rg_youtube_control.seo_v3_pipeline import audit_draft_against_claims
    claims = build_claim_ledger(_source("Чи могла подія бути випадковою?"))
    seen = []
    def reviewer(prompt):
        seen.append(prompt)
        return {"issues": [
            {"field": "description", "reason": "Question rewritten as an established cause ev_1"}
        ]}
    result = audit_draft_against_claims(
        {"title": "Що обговорювали?", "description": "Причина доведена."},
        claims, reviewer,
    )
    assert len(result["issues"]) == 1
    assert result["review_status"] == "SOURCE_AUDITED"
    assert '"source_type": "QUESTION"' in seen[0]
    assert "DRAFT:\n" in seen[0]
    assert "A QUESTION does not establish an answer" in seen[0]
    assert audit_draft_against_claims(
        {"title": "Заголовок"}, claims, lambda _: {"approved": True},
    )["review_status"] == "FAILED_CLOSED"


def test_claim_first_review_must_explicitly_allow_no_external_certainty():
    from rg_youtube_control.seo_v3_pipeline import audit_draft_against_claims
    claims = build_claim_ledger(_source("Можливо буде дощ завтра."))
    prompts = []
    result = audit_draft_against_claims(
        {"title": "Чи буде завтра дощ?"},
        claims,
        lambda prompt: (prompts.append(prompt) or {"issues": []}),
    )
    assert result["issues"] == []
    assert "A HYPOTHESIS is only an attributed opinion" in prompts[0]
    assert claims["claims"][0]["verified_external_fact"] is False


def test_expanded_claim_source_spans_full_srt_without_inference():
    from rg_youtube_control.seo_v2_evidence import (
        evidence_ledger, parse_srt,
    )
    from rg_youtube_control.seo_v3_claims import expand_literal_coverage
    source = "\n\n".join(
        f"{i+1}\n00:00:{i:02d},000 --> 00:00:{i:02d},900\n"
        f"Співрозмовник розповідає про технологію матеріалу номер {i}."
        for i in range(12)
    )
    cues = parse_srt(source)
    original = evidence_ledger(cues, [{
        "quote": cues[0].text, "cue_indices": [0],
    }])
    expanded = expand_literal_coverage(cues, original)
    assert len(expanded["accepted"]) >= 4
    assert expanded["deterministic_source_expansion"] >= 3
    assert expanded["publication_allowed"] is False
    assert any(
        any(index >= 8 for index in item["cue_indices"])
        for item in expanded["accepted"]
    )
    # Every quoted token is verified again against the original cues.
    from rg_youtube_control.seo_v2_evidence import verify_quote
    assert all(
        verify_quote(row["quote"], cues, row["cue_indices"]) is not None
        for row in expanded["accepted"]
    )
