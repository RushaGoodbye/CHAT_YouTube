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
    assert classify_statement("На ваш особистий погляд Какова же Реальная причина увольнения") == "QUESTION"
    assert classify_statement("Він запитав чому компанія змінила рішення") == "QUESTION"
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
    monkeypatch.setattr(
        seo_v3_pipeline, "compose_claim_fields",
        lambda ledger, topics, model: {
            "title": "Реальні причини звільнення директора",
            "title_variants": [
                "Чому директор залишив посаду?",
                "Зміна посади керівника",
                "Що сталося з директором?",
            ],
            "description": "Аналіз доводить причину кадрової зміни. " * 12,
            "tags": ["кадрові зміни"] * 8,
            "support_ids": {
                "title": ["ev_1"],
                "title_variants": [["ev_1"]] * 3,
                "description": ["ev_1"],
                "tags": [["ev_1"]] * 8,
            },
        },
    )
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


def test_three_composers_keep_sentence_and_tag_source_ids():
    from rg_youtube_control.seo_v3_fields import compose_claim_fields
    ledger = build_claim_ledger([
        *_source("Чому не відкрили нову бібліотеку?", "ev_question"),
        *_source("Якщо буде фінансування, відкриємо читальню.", "ev_if"),
    ])
    seen = []
    def chat(prompt):
        seen.append(prompt)
        if "TASK 1 OF 3" in prompt:
            return {
                "title": {
                    "text": "Чому бібліотеку досі не відкрили?",
                    "evidence_ids": ["ev_question"],
                },
                "variants": [
                    {"text": "Питання про бібліотеку", "evidence_ids": ["ev_question"]},
                    {"text": "Чи буде нова читальня?", "evidence_ids": ["ev_if"]},
                    {"text": "За яких умов відкриють читальню?", "evidence_ids": ["ev_if"]},
                ],
            }
        if "TASK 2 OF 3" in prompt:
            return {"sentences": [
                {"text": "У розмові запитують про відкриття бібліотеки.",
                 "evidence_ids": ["ev_question"], "source_type": "QUESTION"},
                {"text": "Співрозмовник пояснює, що читальню відкриють лише за умови фінансування.",
                 "evidence_ids": ["ev_if"], "source_type": "CONDITIONAL"},
                {"text": "Бібліотеку вже відкрито.",
                 "evidence_ids": ["ev_question"], "source_type": "SPEAKER_STATEMENT"},
            ]}
        return {"tags": [
            {"tag": "нова бібліотека", "evidence_ids": ["ev_question"]},
            {"tag": "фінансування читальні", "evidence_ids": ["ev_if"]},
            {"tag": "вигаданий тег", "evidence_ids": ["ev_fake"]},
        ]}
    draft = compose_claim_fields(ledger, [], chat)
    assert len(seen) == 3
    assert len(draft["title_variants"]) == 3
    assert draft["support_ids"]["description"] == ["ev_question", "ev_if"]
    assert "Бібліотеку вже відкрито" not in draft["description"]
    assert draft["tags"] == ["нова бібліотека", "фінансування читальні"]
    assert len(draft["sentence_provenance"]) == 2
    assert all("SOURCE-TYPED CLAIM" in prompt for prompt in seen)


def test_missing_source_references_cannot_be_padded_into_tags():
    from rg_youtube_control.seo_v3_fields import compose_claim_fields
    ledger = build_claim_ledger(_source("Хто займається організацією виставки?"))
    def chat(prompt):
        if "TASK 1 OF 3" in prompt:
            return {"title": {"text": "Хто організує виставку?", "evidence_ids": ["ev_1"]},
                    "variants": []}
        if "TASK 2 OF 3" in prompt:
            return {"sentences": []}
        return {"tags": [{"tag": "непідтверджений сюжет", "evidence_ids": ["ev_no"]}] * 15}
    draft = compose_claim_fields(ledger, [], chat)
    assert draft["tags"] == []
    assert draft["description"] == ""
    assert draft["support_ids"]["tags"] == []


def test_sentence_modality_gate_rejects_unattributed_outcomes():
    from rg_youtube_control.seo_v3_fields import _preserves_modality
    assert _preserves_modality("У розмові запитують, чому це сталося.", "QUESTION")
    assert not _preserves_modality("Причину було остаточно встановлено.", "QUESTION")
    assert _preserves_modality("Якщо буде угода, подію обговорять.", "CONDITIONAL")
    assert not _preserves_modality("Угоду вже остаточно уклали.", "CONDITIONAL")
    assert _preserves_modality("Співрозмовник припускає інше пояснення.", "HYPOTHESIS")
    assert not _preserves_modality("Тепер відома справжня причина.", "HYPOTHESIS")
    assert _preserves_modality("Співрозмовник сказав про рішення.", "SPEAKER_STATEMENT")
    assert not _preserves_modality("Встановлено єдину причину рішення.", "SPEAKER_STATEMENT")


def test_unverified_speaker_statement_cannot_support_claim_of_proven_analysis():
    source = build_claim_ledger(_source("Співрозмовник назвав можливу причину."))
    draft = {
        "title": "Аналіз доводить справжні причини",
        "description": "У розмові згадували різні варіанти.",
        "title_variants": [], "tags": [],
        "support_ids": {"title": ["ev_1"], "description": ["ev_1"]},
    }
    findings = check_claim_type_constraints(draft, source)
    assert any(
        row["field"] == "title"
        and row["reason"] == "UNVERIFIED_OBJECTIVE_CERTAINTY"
        for row in findings
    )


def test_headline_variants_cannot_cite_unrelated_secondary_topic():
    from rg_youtube_control.seo_v3_fields import compose_claim_fields
    ledger = build_claim_ledger([
        *_source("Чому зламався міст?", "ev_main"),
        *_source("Чи з'явиться новий закон?", "ev_side"),
    ])
    topics = [
        {"rank": 1, "label_uk": "Ремонт мосту", "evidence_ids": ["ev_main"]},
        {"rank": 2, "label_uk": "Законопроєкт", "evidence_ids": ["ev_side"]},
    ]
    prompt_log = []
    def chat(prompt):
        prompt_log.append(prompt)
        if "TASK 1 OF 3" in prompt:
            return {
                "title": {"text": "Чому зламався міст?",
                          "evidence_ids": ["ev_main"]},
                "variants": [
                    {"text": "Про новий закон", "evidence_ids": ["ev_side"]},
                    {"text": "Питання ремонту мосту", "evidence_ids": ["ev_main"]},
                    {"text": "Зміни для мосту", "evidence_ids": ["ev_main"]},
                ],
            }
        if "TASK 2 OF 3" in prompt:
            return {"sentences": []}
        return {"tags": []}
    result = compose_claim_fields(ledger, topics, chat)
    assert result["support_ids"]["title"] == ["ev_main"]
    assert result["support_ids"]["title_variants"][0] == []
    assert result["support_ids"]["title_variants"][1] == ["ev_main"]
    assert "ev_side" not in prompt_log[0]
    assert "ev_main" in prompt_log[0]
    assert "ev_side" in prompt_log[1]  # description retains all evidence


def test_short_description_uses_unused_literal_claims_once_without_padding():
    from rg_youtube_control.seo_v3_fields import compose_claim_fields
    ledger = build_claim_ledger([
        *_source("Чому закрили бібліотеку?", "ev_a"),
        *_source("Мовець розповів про відновлення читальні.", "ev_b"),
        *_source("Якщо буде фінансування, відновимо бібліотеку.", "ev_c"),
    ])
    prompts = []
    def model(prompt):
        prompts.append(prompt)
        if "TASK 1 OF 3" in prompt:
            return {"title": {"text": "Чому закрили бібліотеку?", "evidence_ids": ["ev_a"]},
                    "variants": []}
        if "TASK 2 CONTINUATION" in prompt:
            return {"sentences": [
                {"text": "Співрозмовник розповів про відновлення читальні та обговорення умов для її роботи.",
                 "evidence_ids": ["ev_b"], "source_type": "SPEAKER_STATEMENT"},
                {"text": "Якщо з'явиться фінансування, учасник розмови пропонує повернути читальню до роботи.",
                 "evidence_ids": ["ev_c"], "source_type": "CONDITIONAL"},
                {"text": "Влада довела, що будівля вже готова.",
                 "evidence_ids": ["ev_fake"], "source_type": "SPEAKER_STATEMENT"},
            ]}
        if "TASK 2 OF 3" in prompt:
            return {"sentences": [
                {"text": "Співрозмовники запитують, чому раніше було закрито бібліотеку.",
                 "evidence_ids": ["ev_a"], "source_type": "QUESTION"},
            ]}
        return {"tags": []}
    result = compose_claim_fields(ledger, [], model)
    assert any("TASK 2 CONTINUATION" in p for p in prompts)
    assert "Влада довела" not in result["description"]
    assert "відновлення читальні" in result["description"]
    assert result["support_ids"]["description"] == ["ev_a", "ev_b", "ev_c"]
    assert len(result["sentence_provenance"]) == 3


def test_short_description_does_not_invent_claims_if_no_new_evidence():
    from rg_youtube_control.seo_v3_fields import compose_claim_fields
    ledger = build_claim_ledger(_source("Чи знайдуть відповідь?", "ev_a"))
    prompts = []
    def model(prompt):
        prompts.append(prompt)
        if "TASK 1 OF 3" in prompt:
            return {"title": {"text": "Чи знайдуть відповідь?", "evidence_ids": ["ev_a"]},
                    "variants": []}
        if "TASK 2 OF 3" in prompt:
            return {"sentences": [{"text": "У розмові звучить запитання про відповідь.",
                                  "evidence_ids": ["ev_a"], "source_type": "QUESTION"}]}
        return {"tags": []}
    result = compose_claim_fields(ledger, [], model)
    assert "TASK 2 CONTINUATION" not in " ".join(prompts)
    assert len(result["description"]) < 400


def test_search_tags_reject_unrelated_third_topic_evidence():
    from rg_youtube_control.seo_v3_fields import compose_claim_fields
    ledger = build_claim_ledger([
        *_source("Чому на заводі зупинили виробництво?", "ev_a"),
        *_source("Співрозмовник говорить про ремонт заводу.", "ev_b"),
        *_source("Ведучий запитує про випадкового кота.", "ev_cat"),
    ])
    topics = [
        {"rank": 1, "label_uk": "Завод", "evidence_ids": ["ev_a"]},
        {"rank": 2, "label_uk": "Ремонт", "evidence_ids": ["ev_b"]},
        {"rank": 3, "label_uk": "Кіт", "evidence_ids": ["ev_cat"]},
    ]
    seen = []
    def chat(prompt):
        seen.append(prompt)
        if "TASK 1 OF 3" in prompt:
            return {"title": {"text": "Чому зупинили завод?", "evidence_ids": ["ev_a"]},
                    "variants": []}
        if "TASK 2 OF 3" in prompt:
            return {"sentences": []}
        if "TASK 2 CONTINUATION" in prompt:
            return {"sentences": []}
        return {"tags": [
            {"tag": "ремонт заводу", "evidence_ids": ["ev_b"]},
            {"tag": "випадковий кіт", "evidence_ids": ["ev_cat"]},
            {"tag": "причини зупинки заводу", "evidence_ids": ["ev_a"]},
        ]}
    result = compose_claim_fields(ledger, topics, chat)
    assert result["tags"] == ["ремонт заводу", "причини зупинки заводу"]
    assert result["support_ids"]["tags"] == [["ev_b"], ["ev_a"]]
    tag_prompt = next(p for p in seen if "TASK 3 OF 3" in p)
    assert "ev_cat" not in tag_prompt
    assert "ev_b" in tag_prompt


def test_editorial_description_drops_unrelated_third_topic_sentence():
    from rg_youtube_control.seo_v3_fields import compose_claim_fields
    ledger = build_claim_ledger([
        *_source("Чому закрили лікарню?", "ev_main"),
        *_source("Співрозмовник описав медичну допомогу.", "ev_related"),
        *_source("Чи подобається вам музика?", "ev_tangent"),
    ])
    topics = [
        {"rank": 1, "label_uk": "Лікарня", "evidence_ids": ["ev_main"]},
        {"rank": 2, "label_uk": "Медична допомога", "evidence_ids": ["ev_related"]},
        {"rank": 3, "label_uk": "Музика", "evidence_ids": ["ev_tangent"]},
    ]
    seen = []
    def writer(prompt):
        seen.append(prompt)
        if "TASK 1 OF 3" in prompt:
            return {"title": {"text": "Чому закрили лікарню?",
                              "evidence_ids": ["ev_main"]}, "variants": []}
        if "TASK 2 OF 3" in prompt:
            return {"sentences": [
                {"text": "Співрозмовник описав питання медичної допомоги.",
                 "source_type": "SPEAKER_STATEMENT", "evidence_ids": ["ev_related"]},
                {"text": "Було поставлено питання щодо музики.",
                 "source_type": "QUESTION", "evidence_ids": ["ev_tangent"]},
            ]}
        return {"sentences": []} if "TASK 2 CONTINUATION" in prompt else {"tags": []}
    result = compose_claim_fields(ledger, topics, writer)
    assert "медичної допомоги" in result["description"]
    assert "музики" not in result["description"]
    assert result["support_ids"]["description"] == ["ev_related"]
    assert not any("ev_tangent" in prompt for prompt in seen if "TASK 2" in prompt)
