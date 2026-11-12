"""Guardrails for one-pass claim-first SEO v3 field correction."""
from copy import deepcopy

from rg_youtube_control.seo_v3_claims import build_claim_ledger
from rg_youtube_control.seo_v3_repair import repair_claim_fields

PROOF = [
    {"evidence_id": "ev_1", "quote": "Чому звільнили керівника?"},
    {"evidence_id": "ev_2", "quote": "Якщо це покарання, нової посади не буде."},
]
LEDGER = build_claim_ledger(PROOF)


def _draft():
    return {
        "title": "Реальна причина звільнення Шайгурова",
        "title_variants": ["Чому змінили керівника?", "Чи було покарання?", "Що з посадою?"],
        "description": "Співрозмовники обговорюють кадрові зміни. " * 13,
        "tags": ["кадрові зміни", "призначення"],
        "support_ids": {
            "title": ["ev_1"],
            "title_variants": [["ev_1"], ["ev_2"], ["ev_1"]],
            "description": ["ev_1"],
            "tags": [["ev_1"], ["ev_2"]],
        },
    }


def _gate(candidate):
    short = len(candidate["tags"]) < 8
    return {
        "issues": ["EDITORIAL_GATE_FAILED"] if short else [],
        "format": {"problems": {"tags": ["FEWER_THAN_EIGHT"]} if short else {}},
        "editorial": {"issues": {"tags": ["FEWER_THAN_EIGHT"]} if short else {}},
    }


def test_unverified_name_correction_keeps_other_fields_and_citations():
    draft = _draft()
    original = deepcopy(draft)
    calls = []
    def writer(prompt):
        calls.append(prompt)
        return {
            "value": "Чому звільнили керівника?",
            "evidence_ids": ["ev_1"],
        }
    def reviewer(candidate):
        return {"review_status": "SOURCE_AUDITED", "issues": []}
    result, gate, review, diag = repair_claim_fields(
        draft, LEDGER, PROOF, {
            "review_status": "SOURCE_AUDITED",
            "issues": [{"field": "title", "reason": "Unverified personal name"}],
        }, writer, reviewer, _gate, max_fields=1,
    )
    assert diag == {"title": "ACCEPTED"}
    assert result["title"] == "Чому звільнили керівника?"
    assert result["tags"] == original["tags"]
    assert result["support_ids"]["tags"] == original["support_ids"]["tags"]
    assert draft == original
    assert "Шайгурова" in calls[0]


def test_repair_rejects_model_fabricated_source_id():
    draft = _draft()
    result, _, _, diag = repair_claim_fields(
        draft, LEDGER, PROOF, {
            "review_status": "SOURCE_AUDITED",
            "issues": [{"field": "title", "reason": "Wrong name"}],
        }, lambda _: {"value": "Чому звільнили керівника?",
                      "evidence_ids": ["ev_fake"]},
        lambda _: {"review_status": "SOURCE_AUDITED", "issues": []},
        _gate, max_fields=1,
    )
    assert result == draft
    assert diag["title"] == "SOURCE_LINKS_OR_SHAPE_INVALID"


def test_repair_rejects_new_claims_even_with_valid_citation_ids():
    draft = _draft()
    result, _, _, diag = repair_claim_fields(
        draft, LEDGER, PROOF, {
            "review_status": "SOURCE_AUDITED",
            "issues": [{"field": "title", "reason": "Wrong name"}],
        }, lambda _: {"value": "Аналіз доводить реальні причини",
                      "evidence_ids": ["ev_1"]},
        lambda _: {"review_status": "SOURCE_AUDITED", "issues": []},
        _gate, max_fields=1,
    )
    assert result == draft
    assert diag["title"] == "CLAIM_MODALITY_FAILED"


def test_repair_rejects_failed_independent_review():
    draft = _draft()
    result, _, _, diag = repair_claim_fields(
        draft, LEDGER, PROOF, {
            "review_status": "SOURCE_AUDITED",
            "issues": [{"field": "title", "reason": "Wrong name"}],
        }, lambda _: {"value": "Чи стала відставка покаранням?",
                      "evidence_ids": ["ev_2"]},
        lambda _: {"review_status": "SOURCE_AUDITED", "issues": [
            {"field": "title", "reason": "Question implies false premise"}
        ]}, _gate, max_fields=1,
    )
    assert result == draft
    assert diag["title"] == "INDEPENDENT_REVIEW_REJECTED"


def test_missing_tags_fixes_are_triggered_by_format_gate_without_reviewer_prompt():
    draft = _draft()
    def writer(prompt):
        if "FIELD: title\n" in prompt:
            return {"value": None, "evidence_ids": None}
        assert "FEWER_THAN_EIGHT" in prompt
        return {
            "value": [
                "кадрові зміни", "зміна посади", "питання про відставку",
                "призначення", "причини відставки", "високі посади",
                "кадрові рішення", "обговорення відставки",
            ],
            "evidence_ids": [["ev_1"]] * 8,
        }
    def reviewer(_):
        return {"review_status": "SOURCE_AUDITED", "issues": []}
    final, gate, _, diag = repair_claim_fields(
        draft, LEDGER, PROOF,
        {"review_status": "SOURCE_AUDITED", "issues": []},
        writer, reviewer, _gate, max_fields=0,
    )
    assert final == draft
    assert diag == {}
    final, gate, _, diag = repair_claim_fields(
        draft, LEDGER, PROOF,
        {"review_status": "SOURCE_AUDITED", "issues": []},
        writer, reviewer, _gate, max_fields=4,
    )
    assert len(final["tags"]) == 8
    assert not gate["issues"]
    assert diag["tags"] == "ACCEPTED"


def test_failed_closed_independent_audit_disables_all_repairs():
    result, _, _, diag = repair_claim_fields(
        _draft(), LEDGER, PROOF,
        {"review_status": "FAILED_CLOSED",
         "issues": [{"field": "reviewer", "reason": "invalid JSON"}]},
        lambda _: (_ for _ in ()).throw(AssertionError("writer must not run")),
        lambda _: {}, _gate,
    )
    assert diag["reviewer"] == "FAILED_CLOSED"


def test_unrelated_global_name_flag_does_not_block_source_valid_tag_repair():
    draft = _draft()
    def biased_global_gate(candidate):
        if len(candidate["tags"]) < 8:
            return {
                "issues": ["EDITORIAL_GATE_FAILED"],
                "format": {"problems": {"tags": ["FEWER_THAN_EIGHT"]}},
                "editorial": {"issues": {"tags": ["FEWER_THAN_EIGHT"]}},
            }
        return {
            "issues": ["UNVERIFIED_NAMED_ENTITIES"],
            "format": {"problems": {}},
            "editorial": {"issues": {}},
        }
    def writer(prompt):
        if "FIELD: title" in prompt:
            return {"value": None, "evidence_ids": None}
        assert "FIELD: tags\n" in prompt
        return {
            "value": [
                "питання про відставку", "висока посада", "кадрові зміни",
                "обговорення звільнення", "рішення керівника",
                "процедура призначення", "причини зміни посади",
                "питання про кадрові рішення",
            ],
            "evidence_ids": [["ev_1"]] * 8,
        }
    result, gate, review, diag = repair_claim_fields(
        draft, LEDGER, PROOF,
        {"review_status": "SOURCE_AUDITED", "issues": []},
        writer, lambda _: {"review_status": "SOURCE_AUDITED", "issues": []},
        biased_global_gate,
    )
    assert diag["tags"] == "ACCEPTED"
    assert len(result["tags"]) == 8
    assert gate["issues"] == ["UNVERIFIED_NAMED_ENTITIES"]
    assert result["title"] == draft["title"]
