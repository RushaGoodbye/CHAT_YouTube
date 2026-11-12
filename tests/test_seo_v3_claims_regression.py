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


def test_final_sentence_cannot_upgrade_question_to_fact():
    from rg_youtube_control.seo_v3_fields import check_sentence_provenance
    ledger = {"claims": [{"claim_id": "ev_q", "source_type": "QUESTION"}]}
    for text in ("Причину звільнення встановлено.", "Ведучий запитує про причину."):
        draft = {
            "description": text,
            "sentence_provenance": [{"text": text, "evidence_ids": ["ev_q"]}],
            "support_ids": {"description": ["ev_q"]},
        }
        issues = check_sentence_provenance(draft, ledger)
        if text.startswith("Причину"):
            assert issues[0]["reason"] == "SENTENCE_MODALITY_UNSUPPORTED"
        else:
            assert issues == []


def test_final_sentence_preserves_conditional_modality():
    from rg_youtube_control.seo_v3_fields import check_sentence_provenance
    ledger = {"claims": [{"claim_id": "ev_c", "source_type": "CONDITIONAL"}]}
    for text, accepted in [
        ("Покарання вже відбулося.", False),
        ("Якщо це було покаранням, співрозмовники обговорюють наслідки.", True),
    ]:
        draft = {
            "description": text,
            "sentence_provenance": [{"text": text, "evidence_ids": ["ev_c"]}],
            "support_ids": {"description": ["ev_c"]},
        }
        assert (check_sentence_provenance(draft, ledger) == []) == accepted


def test_number_must_appear_in_title_citation_not_elsewhere():
    from rg_youtube_control.seo_v3_numbers import check_cited_numbers
    ledger = {"claims": [
        {"claim_id": "ev_1", "source_quote": "За добу 2400 втрат."},
        {"claim_id": "ev_2", "source_quote": "Говоримо про іншу тему."},
    ]}
    draft = {
        "title": "2400 втрат за добу",
        "title_variants": [], "tags": [],
        "description": "Ведучий говорить про втрати.",
        "sentence_provenance": [
            {"text": "Ведучий говорить про втрати.", "evidence_ids": ["ev_1"]},
        ],
        "support_ids": {"title": ["ev_2"], "description": ["ev_1"],
                        "title_variants": [], "tags": []},
    }
    issues = check_cited_numbers(draft, ledger)
    assert {"field": "title", "reason": "NUMBER_NOT_IN_CITED_QUOTES:2400"} in issues
    draft["support_ids"]["title"] = ["ev_1"]
    assert check_cited_numbers(draft, ledger) == []


def test_numeric_provenance_checks_each_description_sentence_independently():
    from rg_youtube_control.seo_v3_numbers import check_cited_numbers
    ledger = {"claims": [
        {"claim_id": "ev_a", "source_quote": "Показник 1200."},
        {"claim_id": "ev_b", "source_quote": "Інший показник 2300."},
    ]}
    draft = {
        "title": "Розмова про показники", "title_variants": [], "tags": [],
        "description": "Учасник каже 2300.",
        "sentence_provenance": [
            {"text": "Учасник каже 2300.", "evidence_ids": ["ev_a"]},
        ],
        "support_ids": {"title": ["ev_a"], "description": ["ev_a", "ev_b"],
                        "title_variants": [], "tags": []},
    }
    assert {"field": "description", "reason": "NUMBER_NOT_IN_CITED_QUOTES:2300"} in (
        check_cited_numbers(draft, ledger)
    )
    draft["sentence_provenance"][0]["evidence_ids"] = ["ev_b"]
    assert check_cited_numbers(draft, ledger) == []


def test_numeric_provenance_normalizes_decimal_separators():
    from rg_youtube_control.seo_v3_numbers import check_cited_numbers
    ledger = {"claims": [{"claim_id": "ev", "source_quote": "1,6 мільйона."}]}
    draft = {
        "title": "1.6 мільйона", "title_variants": [], "tags": [],
        "description": "Без цифр.", "sentence_provenance": [],
        "support_ids": {"title": ["ev"], "title_variants": [],
                        "tags": [], "description": []},
    }
    assert check_cited_numbers(draft, ledger) == []


def test_repair_uses_deterministic_modality_rejections_even_if_reviewer_passes():
    from rg_youtube_control.seo_v3_repair import repair_claim_fields
    ledger = {"claims": [{
        "claim_id": "ev_1", "source_type": "SPEAKER_STATEMENT",
        "source_quote": "Співрозмовник каже, що причина невідома.",
    }]}
    original = {
        "title": "Реальна причина звільнення",
        "description": "Співрозмовник каже, що причина невідома.",
        "title_variants": ["Що сталося?", "Чому?", "Які запитання?"],
        "tags": ["обговорення"],
        "support_ids": {
            "title": ["ev_1"], "description": ["ev_1"],
            "title_variants": [["ev_1"]] * 3, "tags": [["ev_1"]],
        },
        "sentence_provenance": [{
            "text": "Співрозмовник каже, що причина невідома.",
            "evidence_ids": ["ev_1"],
        }],
    }
    prompts = []
    def writer(prompt):
        prompts.append(prompt)
        return {"value": "Співрозмовник обговорює невідому причину",
                "evidence_ids": ["ev_1"]}
    def reviewer(_):
        return {"review_status": "SOURCE_AUDITED", "issues": []}
    def gate(_):
        return {"issues": [], "format": {"problems": {}},
                "editorial": {"issues": {}}}
    corrected, _, _, diagnostics = repair_claim_fields(
        original, ledger, [], reviewer(original), writer, reviewer, gate)
    assert diagnostics["title"] == "ACCEPTED"
    assert corrected["title"] == "Співрозмовник обговорює невідому причину"
    assert any("UNVERIFIED_OBJECTIVE_CERTAINTY" in prompt for prompt in prompts)


def test_quote_extraction_timeout_uses_literal_verified_srt():
    from rg_youtube_control.seo_v2_pipeline import _extract
    from rg_youtube_control.seo_v2_evidence import Cue
    cues = [
        Cue(0, 1200, "Співрозмовник обговорює новини та ставить питання про події."),
        Cue(1300, 2500, "Ведучий відповідає на запитання про наслідки і причини."),
        Cue(2600, 4000, "Учасники дискутують про різні аспекти почутої історії."),
    ]
    def timed_out(_):
        raise RuntimeError("LM Studio local inference timeout")
    ledger, windows = _extract(cues, timed_out)
    assert len(windows) == 1
    assert ledger["deterministic_fallback_windows"] == [0]
    assert len(ledger["accepted"]) >= 2
    assert all(row["quote"] in [cue.text for cue in cues]
               for row in ledger["accepted"])
    assert ledger["publication_allowed"] is False


def test_quote_extraction_has_shorter_timeout_than_editorial_generation():
    from rg_youtube_control import seo_v2_cli
    original = seo_v2_cli.lm_studio_chat
    captured = []
    def fake_chat(messages, **kwargs):
        captured.append(kwargs["timeout"])
        return "{}"
    seo_v2_cli.lm_studio_chat = fake_chat
    try:
        seo_v2_cli._local_chat(
            "Extract up to three substantial verbatim statements from cues")
        seo_v2_cli._local_chat(
            "Classify the main topics of this portion of the conversation")
        seo_v2_cli._local_chat(
            "Merge overlapping topics of this video")
        seo_v2_cli._local_chat("TASK 1 OF 3: compose a title")
    finally:
        seo_v2_cli.lm_studio_chat = original
    assert captured == [45, 45, 45, 180]


def test_v3_literal_source_extraction_never_calls_model():
    from rg_youtube_control.seo_v3_claims import literal_evidence_from_cues
    from rg_youtube_control.seo_v2_evidence import Cue
    cues = [
        Cue(0, 1200, "Ведучий розповідає про заяву учасника."),
        Cue(1300, 2500, "Співрозмовник питає, чому це відбулося."),
        Cue(2600, 4000, "Учасники обговорюють наслідки різних рішень."),
        Cue(500000, 501000, "Окрема частина розмови присвячена новій темі."),
        Cue(501100, 502300, "Учасник запитує про обставини іншого випадку."),
    ]
    ledger, windows = literal_evidence_from_cues(cues)
    assert len(windows) == 2
    assert ledger["deterministic_source_only"] is True
    assert ledger["windows_without_quotes"] == []
    assert len(ledger["accepted"]) >= 2
    assert all(row["quote"] in [cue.text for cue in cues]
               for row in ledger["accepted"])
    assert ledger["publication_allowed"] is False


def test_description_repair_normalizes_whitespace_only_drift():
    from rg_youtube_control.seo_v3_repair import repair_claim_fields
    ledger = {"claims": [{"claim_id": "ev_1", "source_type": "QUESTION",
                          "source_quote": "Чому це сталося?"}]}
    original = {
        "title": "Чому?", "title_variants": ["Чому?", "Що?", "Як?"],
        "description": "Короткий текст.", "tags": ["причина"],
        "support_ids": {
            "title": ["ev_1"], "title_variants": [["ev_1"]] * 3,
            "description": ["ev_1"], "tags": [["ev_1"]],
        },
        "sentence_provenance": [{"text": "Короткий текст.", "evidence_ids": ["ev_1"]}],
    }
    first = "Ведучий запитує про причини."
    second = "Учасник обговорює запитання."
    def writer(_):
        return {
            "value": first + "\n" + second,
            "evidence_ids": ["ev_1"],
            "sentences": [
                {"text": first, "evidence_ids": ["ev_1"]},
                {"text": second, "evidence_ids": ["ev_1"]},
            ],
        }
    def reviewer(_):
        return {"review_status": "SOURCE_AUDITED", "issues": []}
    def gate(_):
        return {"issues": [], "format": {"problems": {}},
                "editorial": {"issues": {}}}
    corrected, _, _, diagnostics = repair_claim_fields(
        original, ledger, [], {"review_status": "SOURCE_AUDITED",
            "issues": [{"field": "description", "reason": "short description"}]},
        writer, reviewer, gate,
    )
    assert diagnostics["description"] == "ACCEPTED"
    assert corrected["description"] == first + " " + second


def test_description_repair_refuses_changed_words_in_sentence_list():
    from rg_youtube_control.seo_v3_repair import repair_claim_fields
    ledger = {"claims": [{"claim_id": "ev_1", "source_type": "QUESTION",
                          "source_quote": "Чому це сталося?"}]}
    original = {
        "title": "Чому?", "title_variants": ["Чому?", "Що?", "Як?"],
        "description": "Короткий текст.", "tags": ["причина"],
        "support_ids": {
            "title": ["ev_1"], "title_variants": [["ev_1"]] * 3,
            "description": ["ev_1"], "tags": [["ev_1"]],
        },
        "sentence_provenance": [{"text": "Короткий текст.", "evidence_ids": ["ev_1"]}],
    }
    def writer(_):
        return {
            "value": "Ведучий запитує про причини.",
            "evidence_ids": ["ev_1"],
            "sentences": [{"text": "Ведучий підтвердив причини.", "evidence_ids": ["ev_1"]}],
        }
    def reviewer(_):
        return {"review_status": "SOURCE_AUDITED", "issues": []}
    def gate(_):
        return {"issues": [], "format": {"problems": {}},
                "editorial": {"issues": {}}}
    corrected, _, _, diagnostics = repair_claim_fields(
        original, ledger, [], {"review_status": "SOURCE_AUDITED",
            "issues": [{"field": "description", "reason": "unsupported"}]},
        writer, reviewer, gate,
    )
    assert diagnostics["description"] == "DESCRIPTION_PROVENANCE_INVALID"
    assert corrected["description"] == original["description"]


def test_topic_model_timeout_preserves_literal_evidence_without_fake_events():
    from rg_youtube_control.seo_v2_pipeline import _select_topics
    ledger = {"accepted": [
        {"evidence_id": f"ev_{i}", "quote": f"Співрозмовник обговорює тему {i}."}
        for i in range(10)
    ]}
    prompts = []
    def fail(prompt):
        prompts.append(prompt)
        raise RuntimeError("LM Studio local inference timeout")
    topics = _select_topics(ledger, fail)
    assert topics
    assert all(topic.get("topic_fallback") is True for topic in topics)
    assert set(eid for item in topics for eid in item["evidence_ids"]) == {
        f"ev_{i}" for i in range(10)
    }
    assert all(topic["label_uk"] == "Теми розмови" for topic in topics)
    assert all("start_ms" not in prompt and "cue_indices" not in prompt
               for prompt in prompts)


def test_genuine_unanswered_cause_question_not_equated_with_proven_cause():
    from rg_youtube_control.seo_v3_claims import check_claim_type_constraints
    ledger = {"claims": [{"claim_id": "ev", "source_type": "QUESTION",
                          "source_quote": "Чому його звільнили?"}]}
    draft = {
        "title": "Яка справжня причина звільнення?",
        "title_variants": [], "description": "",
        "tags": [],
        "support_ids": {"title": ["ev"], "description": ["ev"]},
    }
    assert not any(x["reason"] == "UNVERIFIED_OBJECTIVE_CERTAINTY"
                   for x in check_claim_type_constraints(draft, ledger))
    draft["title"] = "Справжня причина звільнення відома"
    assert any(x["reason"] == "UNVERIFIED_OBJECTIVE_CERTAINTY"
               for x in check_claim_type_constraints(draft, ledger))
    draft["title"] = "Справжня причина звільнення?"
    assert any(x["reason"] == "UNVERIFIED_OBJECTIVE_CERTAINTY"
               for x in check_claim_type_constraints(draft, ledger))


def test_topic_output_budget_is_bounded_without_reducing_editorial_budget():
    from rg_youtube_control import seo_v2_cli
    original = seo_v2_cli.lm_studio_chat
    observed = []
    def mock(messages, **kwargs):
        observed.append((kwargs["timeout"], kwargs["max_tokens"]))
        return "{}"
    seo_v2_cli.lm_studio_chat = mock
    try:
        seo_v2_cli._local_chat("Classify the main topics for source quotations")
        seo_v2_cli._local_chat("TASK 2 OF 3: write detailed source-cited description")
    finally:
        seo_v2_cli.lm_studio_chat = original
    assert observed == [(45, 850), (180, 4000)]
