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
    assert diagnostics["description"].startswith("DESCRIPTION_PROVENANCE_INVALID:")


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
    assert captured == [45, 45, 45, 100]


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
    assert diagnostics["description"].startswith("DESCRIPTION_PROVENANCE_INVALID:")
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
    assert observed == [(45, 650), (150, 2400)]


def test_independent_auditor_sees_only_quoted_sources_cited_by_draft():
    from rg_youtube_control.seo_v3_pipeline import audit_draft_against_claims
    claims = {"claims": [
        {"claim_id": "ev_a", "source_type": "QUESTION", "source_quote": "Чому?"},
        {"claim_id": "ev_b", "source_type": "QUESTION",
         "source_quote": "Непов'язана розмова про іншу подію"},
    ]}
    draft = {
        "title": "Про що запитали?", "title_variants": ["Що?", "Як?", "Коли?"],
        "description": "Ведучий ставить питання.", "tags": ["запитання"],
        "support_ids": {
            "title": ["ev_a"],
            "description": ["ev_a"],
            "title_variants": [["ev_a"], ["ev_a"], ["ev_a"]],
            "tags": [["ev_a"]],
        },
    }
    observed = []
    def fake_reviewer(prompt):
        observed.append(prompt)
        return {"issues": []}
    result = audit_draft_against_claims(draft, claims, fake_reviewer)
    assert result["review_status"] == "SOURCE_AUDITED"
    assert '"claim_id": "ev_a"' in observed[0]
    assert '"claim_id": "ev_b"' not in observed[0]
    assert "Непов'язана розмова" not in observed[0]


def test_long_srt_topic_selection_has_five_timeline_spread_model_calls():
    from rg_youtube_control.seo_v2_pipeline import _select_topics
    proof = [{"evidence_id": f"ev_{i:03d}",
              "quote": f"Розмова про питання номер {i}."}
             for i in range(240)]
    seen = []
    def respond(prompt):
        if prompt.startswith("Classify the main topics"):
            import json
            data = json.loads(prompt.split("VERBATIM EVIDENCE:\n", 1)[1])
            seen.append([row["evidence_id"] for row in data])
            return {"topics": [{"label_uk": "Розмова про питання",
                                "evidence_ids": [data[0]["evidence_id"]]}]}
        return {"topics": [{"label_uk": "Підсумок розмови",
                            "evidence_ids": []}]}
    topics = _select_topics({"accepted": proof}, respond)
    assert len(seen) == 5
    assert seen[0][0] == "ev_000"
    assert seen[-1][0] == "ev_232"
    assert topics


def test_topic_classification_timeout_triggers_one_backend_attempt():
    from rg_youtube_control.seo_v2_pipeline import _select_topics
    proof = [{"evidence_id": f"ev_{i}", "quote": f"Тема розмови {i}."}
             for i in range(160)]
    calls = []
    def fail(prompt):
        calls.append(prompt)
        raise RuntimeError("LM Studio local inference timeout")
    topics = _select_topics({"accepted": proof}, fail)
    assert len(calls) == 1
    assert topics
    assert all(item.get("topic_fallback") for item in topics)


def test_lmstudio_http400_compatibility_retry_never_leaks_or_ignores_context_errors():
    from rg_youtube_control import lm_studio_client as client
    original = client._local_json
    calls = []
    def mock(endpoint, *, base_url, payload=None, timeout=0, token=""):
        calls.append(dict(payload))
        if len(calls) < 3:
            raise RuntimeError("LM Studio local HTTP 400: REQUEST_REJECTED")
        return {"choices": [{"message": {"content": '{"ok":true}'}}]}
    client._local_json = mock
    try:
        value = client.lm_studio_chat(
            [{"role": "user", "content": "Return JSON"}],
            model="local-model", json_mode=True, reasoning_effort="none")
    finally:
        client._local_json = original
    assert value == '{"ok":true}'
    assert len(calls) == 3
    assert "reasoning_effort" in calls[0]
    assert "reasoning_effort" not in calls[1]
    assert "response_format" not in calls[2]
    assert all(x["messages"][0]["content"] == "Return JSON" for x in calls)

    blocked = []
    def context_fail(endpoint, *, base_url, payload=None, timeout=0, token=""):
        blocked.append(1)
        raise RuntimeError("LM Studio local HTTP 400: CONTEXT_LIMIT")
    client._local_json = context_fail
    try:
        try:
            client.lm_studio_chat(
                [{"role": "user", "content": "Return JSON"}],
                model="local-model", json_mode=True)
        except RuntimeError as exc:
            assert "CONTEXT_LIMIT" in str(exc)
        else:
            raise AssertionError("CONTEXT_LIMIT_MUST_FAIL_CLOSED")
    finally:
        client._local_json = original
    assert len(blocked) == 1


def test_lmstudio_headline_stage_uses_bounded_request_budget():
    from rg_youtube_control import seo_v2_cli
    original = seo_v2_cli.lm_studio_chat
    seen = []
    def mock(messages, **kwargs):
        seen.append((kwargs["timeout"], kwargs["max_tokens"]))
        return "{}"
    seo_v2_cli.lm_studio_chat = mock
    try:
        seo_v2_cli._local_chat("TASK 1 OF 3: write title and three A/B options")
        seo_v2_cli._local_chat("TASK 3 OF 3: write cited tags")
        seo_v2_cli._local_chat(
            "You are a skeptical, INDEPENDENT Ukrainian SEO source auditor.")
    finally:
        seo_v2_cli.lm_studio_chat = original
    assert seen == [(100, 1100), (120, 1400), (135, 1800)]


def test_source_topic_ranking_uses_only_literal_ids_without_model():
    from rg_youtube_control.seo_v3_claims import select_source_topics_without_llm
    rows = [
        {"evidence_id": "ev_a", "quote": "Учасники обговорюють нафтопереробний завод і пожежу."},
        {"evidence_id": "ev_b", "quote": "Ведучий питає про нафтопереробний завод."},
        {"evidence_id": "ev_c", "quote": "Мовець розповідає про футбольний матч."},
        {"evidence_id": "ev_d", "quote": "Співрозмовник повертається до теми пожежі на заводі."},
        {"evidence_id": "ev_e", "quote": "Інший учасник згадує футбольний матч."},
    ]
    topics = select_source_topics_without_llm({"accepted": rows}, group_size=2)
    assert topics and len(topics) <= 3
    assert all(topic["selection_method"] == "verbatim_lexical_overlap"
               for topic in topics)
    assert all(topic["label_uk"].startswith("Цитати з розмови")
               for topic in topics)
    all_ids = {row["evidence_id"] for row in rows}
    assert {eid for t in topics for eid in t["evidence_ids"]} <= all_ids
    assert len({eid for t in topics for eid in t["evidence_ids"]}) == len(rows)
    assert all(len(t["evidence_ids"]) <= 2 for t in topics)


def test_pipeline_does_not_request_model_for_verbatim_quote_topic_selection():
    from rg_youtube_control import seo_v3_pipeline
    from rg_youtube_control.seo_v2_evidence import parse_srt
    srt = ("1\n00:00:00,000 --> 00:00:01,500\n"
           "Ведучий обговорює причини рішення.\n\n"
           "2\n00:00:01,501 --> 00:00:03,000\n"
           "Співрозмовник запитує про рішення.")
    calls = []
    def chat(prompt):
        calls.append(prompt)
        raise RuntimeError("Stop at first requested model stage")
    try:
        seo_v3_pipeline.generate_claim_first_seo(srt, chat)
    except RuntimeError:
        pass
    assert calls and calls[0].find("TASK 1 OF 3:") != -1
    assert not any("Classify the main topics" in p for p in calls)


def test_description_question_does_not_license_unrelated_assertion():
    from rg_youtube_control.seo_v3_claims import check_claim_type_constraints
    ledger = {"claims": [
        {"claim_id": "ev_q", "source_type": "QUESTION",
         "source_quote": "Чому це відбулося?"},
        {"claim_id": "ev_s", "source_type": "SPEAKER_STATEMENT",
         "source_quote": "Учасники обговорюють подію."},
    ]}
    question = "Ведучий запитує, яка справжня причина події?"
    assertion = "Справжня причина події встановлена."
    draft = {
        "title": "Про що питають?", "title_variants": [], "tags": [],
        "description": question + " " + assertion,
        "support_ids": {"title": ["ev_q"],
                        "description": ["ev_q", "ev_s"]},
        "sentence_provenance": [
            {"text": question, "evidence_ids": ["ev_q"]},
            {"text": assertion, "evidence_ids": ["ev_s"]},
        ],
    }
    problems = check_claim_type_constraints(draft, ledger)
    assert any(row["field"] == "description" and
               row["reason"] == "UNVERIFIED_OBJECTIVE_CERTAINTY"
               for row in problems)
    draft["description"] = question
    draft["sentence_provenance"] = [{"text": question, "evidence_ids": ["ev_q"]}]
    assert not any(row["reason"] == "UNVERIFIED_OBJECTIVE_CERTAINTY"
                   for row in check_claim_type_constraints(draft, ledger))


def test_description_repair_rebuilds_from_cited_sentences_then_reaudits():
    from rg_youtube_control.seo_v3_repair import repair_claim_fields
    ledger = {"claims": [
        {"claim_id": "ev_q", "source_type": "QUESTION",
         "source_quote": "Чому це сталося?"}
    ]}
    old = {
        "title": "Про що запитали?",
        "title_variants": ["Які питання?", "Що відомо?", "Про що розмова?"],
        "description": "Надто короткий опис.",
        "tags": ["обговорення"],
        "support_ids": {
            "title": ["ev_q"],
            "title_variants": [["ev_q"]] * 3,
            "description": ["ev_q"],
            "tags": [["ev_q"]],
        },
        "sentence_provenance": [
            {"text": "Надто короткий опис.", "evidence_ids": ["ev_q"]}
        ],
    }
    sentences = [
        {"text": "Ведучий запитує, чому відбулася ця подія?",
         "evidence_ids": ["ev_q"]},
        {"text": "Учасник обговорює запитання про причини.",
         "evidence_ids": ["ev_q"]},
    ]
    def writer(_):
        return {
            "value": "Зайва модельна версія, яка не є частиною речень.",
            "evidence_ids": ["ev_q"],
            "sentences": sentences,
        }
    reviewed = []
    def reviewer(draft):
        reviewed.append(draft["description"])
        return {"review_status": "SOURCE_AUDITED", "issues": []}
    def gate(_):
        return {"issues": [], "format": {"problems": {}},
                "editorial": {"issues": {}}}
    result, _, _, diagnostics = repair_claim_fields(
        old, ledger, [], {
            "review_status": "SOURCE_AUDITED",
            "issues": [{"field": "description", "reason": "Too short"}],
        }, writer, reviewer, gate,
    )
    expected = " ".join(s["text"] for s in sentences)
    assert diagnostics["description"] == "ACCEPTED"
    assert result["description"] == expected
    assert reviewed == [expected]


def test_description_repair_rejects_mismatched_sentence_source_ids():
    from rg_youtube_control.seo_v3_repair import repair_claim_fields
    ledger = {"claims": [
        {"claim_id": "ev_q", "source_type": "QUESTION",
         "source_quote": "Чому це сталося?"},
        {"claim_id": "ev_other", "source_type": "QUESTION",
         "source_quote": "Куди йти?"},
    ]}
    old = {
        "title": "Чому?", "title_variants": ["Що?", "Коли?", "Як?"],
        "description": "Коротко.", "tags": ["питання"],
        "support_ids": {
            "title": ["ev_q"], "title_variants": [["ev_q"]] * 3,
            "description": ["ev_q"], "tags": [["ev_q"]],
        },
        "sentence_provenance": [
            {"text": "Коротко.", "evidence_ids": ["ev_q"]}
        ],
    }
    def writer(_):
        return {
            "value": "Ведучий запитує, чому?",
            "evidence_ids": ["ev_other"],
            "sentences": [{
                "text": "Ведучий запитує, чому?", "evidence_ids": ["ev_q"]
            }],
        }
    def reviewer(_):
        raise AssertionError("Mismatched source IDs must never reach review")
    def gate(_):
        return {"issues": [], "format": {"problems": {}},
                "editorial": {"issues": {}}}
    result, _, _, diag = repair_claim_fields(
        old, ledger, [], {
            "review_status": "SOURCE_AUDITED",
            "issues": [{"field": "description", "reason": "Too short"}],
        }, writer, reviewer, gate,
    )
    assert diag["description"].startswith("DESCRIPTION_PROVENANCE_INVALID:")
    assert result["description"] == old["description"]


def test_explicit_ukrainian_attribution_forms_pass_modality_without_claiming_truth():
    from rg_youtube_control.seo_v3_fields import _preserves_modality
    valid = {
        "QUESTION": ["Співрозмовник цікавиться, чому це відбулося.",
                     "Ведучий розпитує про деталі події."],
        "SPEAKER_STATEMENT": [
            "Учасник пояснив свою позицію щодо події.",
            "Ведучий наголосив на своєму припущенні.",
            "Співрозмовник розповів про свій досвід.",
        ],
        "HYPOTHESIS": [
            "Ведучий міркує про можливі наслідки.",
            "Учасник висловив припущення про причини.",
        ],
        "CONDITIONAL": [
            "У разі такого рішення ситуація могла б змінитися.",
        ],
    }
    for kind, examples in valid.items():
        for sentence in examples:
            assert _preserves_modality(sentence, kind), (kind, sentence)
    # A bare unsupported assertion still must fail every source-type guard.
    for kind in valid:
        assert not _preserves_modality("Причину події доведено.", kind)


def test_sentence_provenance_accepts_attributed_speaker_but_rejects_bare_assertion():
    from rg_youtube_control.seo_v3_fields import check_sentence_provenance
    ledger = {"claims": [{
        "claim_id": "ev_1",
        "source_type": "SPEAKER_STATEMENT",
        "source_quote": "Я вам про це розповідав.",
    }]}
    text = "Учасник пояснив своє бачення події."
    draft = {
        "description": text,
        "sentence_provenance": [{"text": text, "evidence_ids": ["ev_1"]}],
        "support_ids": {"description": ["ev_1"]},
    }
    assert check_sentence_provenance(draft, ledger) == []
    draft["description"] = "Обставини події доведені."
    draft["sentence_provenance"][0]["text"] = draft["description"]
    assert check_sentence_provenance(draft, ledger)[0]["reason"] == "SENTENCE_MODALITY_UNSUPPORTED"
