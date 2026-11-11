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
