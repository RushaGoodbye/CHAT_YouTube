"""Regression coverage for embedded interrogatives in source-typed SEO v3."""
from rg_youtube_control.seo_v3_claims import classify_statement


def test_embedded_interrogatives_are_questions():
    for spoken in (
        "Ну а почему он ушел",
        "Так скажите, чому це сталося",
        "Давайте разберёмся, сколько это стоило",
        "Мене цікавить, хто це сказав",
    ):
        assert classify_statement(spoken) == "QUESTION", spoken


def test_question_word_inside_another_word_is_not_a_question():
    assert classify_statement("Це історія про непочему") == "SPEAKER_STATEMENT"


def test_conditional_and_hypothesis_remain_distinct():
    assert classify_statement("Если бы это произошло, всё изменилось") == "CONDITIONAL"
    assert classify_statement("Возможно, это другое объяснение") == "HYPOTHESIS"


def test_explicit_question_still_detected():
    assert classify_statement("Ви бачили це?") == "QUESTION"


def test_unverified_real_cause_claims_are_flagged():
    from rg_youtube_control.seo_v3_claims import check_claim_type_constraints
    ledger = {"claims": [{"claim_id": "ev_1", "source_type": "SPEAKER_STATEMENT"}]}
    for phrase in ("Реальна причина звільнення", "Справжня причина звільнення",
                   "Реальні причини звільнення"):
        draft = {
            "title": phrase, "title_variants": [], "description": "",
            "tags": [],
            "support_ids": {"title": ["ev_1"], "description": ["ev_1"]}
        }
        issues = check_claim_type_constraints(draft, ledger)
        assert any(issue["field"] == "title" and
                   issue["reason"] == "UNVERIFIED_OBJECTIVE_CERTAINTY"
                   for issue in issues), phrase


def test_sentence_provenance_rejects_stale_description():
    from rg_youtube_control.seo_v3_fields import check_sentence_provenance
    ledger = {"claims": [{"claim_id": "ev_1", "source_type": "QUESTION"}]}
    draft = {
        "description": "Ведучий запитує про причини.",
        "sentence_provenance": [
            {"text": "Ведучий запитує про причини.", "evidence_ids": ["ev_1"]},
        ],
        "support_ids": {"description": ["ev_1"]},
    }
    assert check_sentence_provenance(draft, ledger) == []
    draft["description"] = "Причини вже доведено."
    assert check_sentence_provenance(draft, ledger)[0]["reason"] == "SENTENCE_TEXT_OUT_OF_SYNC"


def test_sentence_provenance_rejects_missing_or_unknown_claims():
    from rg_youtube_control.seo_v3_fields import check_sentence_provenance
    ledger = {"claims": [{"claim_id": "ev_1", "source_type": "QUESTION"}]}
    draft = {
        "description": "Ведучий запитує про причини.",
        "sentence_provenance": [
            {"text": "Ведучий запитує про причини.", "evidence_ids": ["ev_fake"]},
        ],
        "support_ids": {"description": ["ev_fake"]},
    }
    assert check_sentence_provenance(draft, ledger)[0]["reason"] == "SENTENCE_SOURCE_INVALID"
    draft["sentence_provenance"] = []
    assert check_sentence_provenance(draft, ledger)[0]["reason"] == "SENTENCE_PROVENANCE_MISSING"


def test_sentence_provenance_rejects_parallel_id_drift():
    from rg_youtube_control.seo_v3_fields import check_sentence_provenance
    ledger = {"claims": [
        {"claim_id": "ev_1", "source_type": "QUESTION"},
        {"claim_id": "ev_2", "source_type": "SPEAKER_STATEMENT"},
    ]}
    draft = {
        "description": "Співрозмовник ставить запитання.",
        "sentence_provenance": [
            {"text": "Співрозмовник ставить запитання.", "evidence_ids": ["ev_1"]},
        ],
        "support_ids": {"description": ["ev_2"]},
    }
    assert check_sentence_provenance(draft, ledger)[0]["reason"] == "SENTENCE_IDS_OUT_OF_SYNC"


def test_description_repair_refuses_missing_sentence_provenance():
    from rg_youtube_control.seo_v3_repair import repair_claim_fields
    ledger = {"claims": [{"claim_id": "ev_1", "source_type": "QUESTION",
                          "source_quote": "Чому це сталося?"}]}
    original = {
        "title": "Чому?",
        "title_variants": ["Чому?", "Що сталося?", "Які причини?"],
        "description": "Ведучий запитує про причини.",
        "tags": ["питання про причини"],
        "support_ids": {
            "title": ["ev_1"], "title_variants": [["ev_1"]] * 3,
            "description": ["ev_1"], "tags": [["ev_1"]],
        },
        "sentence_provenance": [
            {"text": "Ведучий запитує про причини.", "evidence_ids": ["ev_1"]},
        ],
    }
    def writer(_prompt):
        return {"value": "Співрозмовник обговорює причини.",
                "evidence_ids": ["ev_1"]}
    def reviewer(_candidate):
        return {"review_status": "SOURCE_AUDITED", "issues": []}
    def gate(_candidate):
        return {"issues": [], "format": {"problems": {}},
                "editorial": {"issues": {}}}
    result, _, _, diagnostics = repair_claim_fields(
        original, ledger, [], {"review_status": "SOURCE_AUDITED",
                               "issues": [{"field": "description",
                                           "reason": "Unsupported assertion"}]},
        writer, reviewer, gate)
    assert result["description"] == original["description"]
    assert diagnostics["description"] == "DESCRIPTION_PROVENANCE_INVALID"


def test_description_repair_accepts_exact_sentence_provenance():
    from rg_youtube_control.seo_v3_repair import repair_claim_fields
    ledger = {"claims": [{"claim_id": "ev_1", "source_type": "QUESTION",
                          "source_quote": "Чому це сталося?"}]}
    original = {
        "title": "Чому?",
        "title_variants": ["Чому?", "Що сталося?", "Які причини?"],
        "description": "Неперевірене твердження.",
        "tags": ["питання про причини"],
        "support_ids": {
            "title": ["ev_1"], "title_variants": [["ev_1"]] * 3,
            "description": ["ev_1"], "tags": [["ev_1"]],
        },
        "sentence_provenance": [
            {"text": "Неперевірене твердження.", "evidence_ids": ["ev_1"]},
        ],
    }
    def writer(_prompt):
        text = "Ведучий запитує про причини."
        return {"value": text, "evidence_ids": ["ev_1"],
                "sentences": [{"text": text, "evidence_ids": ["ev_1"]}]}
    def reviewer(_candidate):
        return {"review_status": "SOURCE_AUDITED", "issues": []}
    def gate(_candidate):
        return {"issues": [], "format": {"problems": {}},
                "editorial": {"issues": {}}}
    result, _, _, diagnostics = repair_claim_fields(
        original, ledger, [], {"review_status": "SOURCE_AUDITED",
                               "issues": [{"field": "description", "reason": "Unsupported"}]},
        writer, reviewer, gate)
    assert diagnostics["description"] == "ACCEPTED"
    assert result["description"] == "Ведучий запитує про причини."
    assert result["sentence_provenance"][0]["evidence_ids"] == ["ev_1"]
