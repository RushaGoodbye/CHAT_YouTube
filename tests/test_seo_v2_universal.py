"""Universal SEO v2 regression: arbitrary topics, quote provenance, no publishing."""
import json

from rg_youtube_control.seo_v2_evidence import (
    evidence_ledger, make_windows, parse_srt, verify_quote,
)
from rg_youtube_control.seo_v2_pipeline import (
    generate_universal_seo, validate_draft,
)


def _srt(words):
    return "\n\n".join(
        f"{i + 1}\n00:00:{i:02d},000 --> 00:00:{i:02d},800\n{line}"
        for i, line in enumerate(words)
    )


def test_ingest_covers_all_cues_and_tail_without_topic_assumptions():
    cues = parse_srt(_srt([
        "Говорили про відновлення мосту.",
        "Мистецтво стало темою суперечки.",
        "Згадали погоду та прогноз.",
    ]))
    assert len(cues) == 3
    windows = make_windows(cues, max_chars=100)
    assert [i for group in windows for i in group] == [0, 1, 2]


def test_ledger_rejects_invented_quote_and_unrelated_cues():
    cues = parse_srt(_srt([
        "Ми говорили про будівництво мосту.",
        "Співрозмовник розповів про погоду.",
    ]))
    accepted = verify_quote("Ми говорили про будівництво мосту.", cues, [0])
    assert accepted is not None and accepted.cue_indices == (0,)
    assert verify_quote("Вони виграли вибори.", cues, [0, 1]) is None
    result = evidence_ledger(cues, [
        {"quote": "Ми говорили про будівництво мосту.", "cue_indices": [0]},
        {"quote": "Вони виграли вибори.", "cue_indices": [0]},
    ])
    assert len(result["accepted"]) == 1
    assert len(result["rejected"]) == 1
    assert result["publication_allowed"] is False


def test_review_gate_rejects_forged_citations_and_numbers():
    cues = parse_srt(_srt(["Ми говорили про архітектуру міста."]))
    ledger = evidence_ledger(cues, [{
        "quote": "Ми говорили про архітектуру міста.", "cue_indices": [0],
    }])
    draft = {
        "title": "Архітектура міста та 1234 нові будівлі",
        "title_variants": ["Перша назва", "Друга назва", "Третя назва"],
        "description": "Міська архітектура і будинки.",
        "tags": ["місто"],
        "support_ids": {
            "title": ["ev_unverified"],
            "description": ["ev_unverified"],
            "title_variants": [["ev_unverified"]] * 3,
            "tags": [["ev_unverified"]],
        },
    }
    gate = validate_draft(draft, ledger, cues)
    assert "UNSUPPORTED_NUMBERS" in gate["issues"]
    assert "TITLE_UNSUPPORTED" in gate["issues"]
    assert "FORMAT_GATE_FAILED" in gate["issues"]
    assert gate["publication_allowed"] is False


def test_v2_accepts_any_content_without_hardcoded_keyword_list():
    source = _srt([
        "Кераміст розповідає про традиційну глазур та випалювання.",
        "Під час розмови згадували особливості глазурування кераміки.",
        "Майстер порівнює способи випалювання керамічних виробів.",
    ])
    state = {"calls": 0, "id": ""}
    def chat(prompt):
        state["calls"] += 1
        if "Extract up to three" in prompt:
            data = json.loads(prompt.split("SOURCE CUES:\n", 1)[1])
            row = data[0]
            return {"quotes": [{"quote": row["text"], "cue_indices": [row["cue"]]}]}
        if "Classify the main topics" in prompt:
            data = json.loads(prompt.split("EVIDENCE:\n", 1)[1])
            state["id"] = data[0]["evidence_id"]
            return {"topics": [{
                "label_uk": "Глазурування та випалювання кераміки",
                "evidence_ids": [item["evidence_id"] for item in data],
            }]}
        if "You are an accurate" in prompt:
            eid = state["id"]
            return {
                "title": "Як майстер створює кераміку: глазур і випалювання",
                "title_variants": [
                    "Особливості глазурування кераміки",
                    "Кераміка: від глазурування до випалу",
                    "Як випалюють керамічні вироби",
                ],
                "description": "У розмові йдеться про кераміку, глазурування та випалювання. " * 8,
                "tags": [
                    "глазурування кераміки", "випалювання кераміки",
                    "майстер кераміки", "керамічні вироби",
                    "традиційна глазур", "процес випалювання",
                    "вироби з кераміки", "випал кераміки",
                ],
                "support_ids": {
                    "title": [eid], "description": [eid],
                    "title_variants": [[eid]] * 3, "tags": [[eid]] * 8,
                },
            }
        raise AssertionError("Unexpected model prompt")
    result = generate_universal_seo(
        source, chat,
        independent_review=lambda _prompt: {"issues": []},
    )
    assert result["draft"]["title"].startswith("Як майстер")
    assert result["topics"][0]["label_uk"].startswith("Глазурування")
    assert result["status"] in {"REVIEW_REQUIRED", "READY_FOR_HUMAN_REVIEW"}
    assert result["publication_allowed"] is False
    assert result["editorial_approved"] is False
    assert result["evidence"]["source_cues"] == 3


def test_topic_map_reduce_is_bounded_and_all_citations_are_real():
    from rg_youtube_control.seo_v2_pipeline import _select_topics
    evidence = [{
        "evidence_id": f"ev_{i:016d}",
        "quote": f"Майстер пояснює техніку малювання номер {i}.",
        "start_ms": i * 1000,
        "end_ms": i * 1000 + 500,
        "cue_indices": [i],
    } for i in range(96)]
    seen_sizes = []
    def chat(prompt):
        if "VERBATIM EVIDENCE:\n" in prompt:
            batch = json.loads(prompt.split("VERBATIM EVIDENCE:\n", 1)[1])
            seen_sizes.append(len(batch))
            return {"topics": [
                {"label_uk": "Техніка малювання", "evidence_ids": [row["evidence_id"]]}
                for row in batch[:4]
            ]}
        batch = json.loads(prompt.split("TOPIC MAP:\n", 1)[1])
        seen_sizes.append(len(batch))
        return {"topics": [
            {"label_uk": "Художні техніки", "evidence_ids": [
                evidence_id
                for entry in batch[:2]
                for evidence_id in entry["evidence_ids"]
            ]}
        ]}
    topics = _select_topics({"accepted": evidence}, chat)
    assert 1 <= len(topics) <= 5
    assert max(seen_sizes) <= 16
    assert all(
        item in {x["evidence_id"] for x in evidence}
        for topic in topics for item in topic["evidence_ids"]
    )


def test_fallback_recovers_skipped_window_using_only_verbatim_cues(monkeypatch):
    from rg_youtube_control import seo_v2_pipeline
    from rg_youtube_control.seo_v2_pipeline import _extract
    cue_text = [
        "Майстер розповідає про техніку роботи з металом.",
        "Далі він обговорює спільну роботу майстрів.",
        "Після цього мова йде про обробку матеріалів.",
    ]
    cues = parse_srt(_srt(cue_text))
    windows = make_windows(cues, max_chars=100)
    assert len(windows) >= 2
    monkeypatch.setattr(
        seo_v2_pipeline, "make_windows",
        lambda source: make_windows(source, max_chars=100),
    )
    def chat(prompt):
        data = json.loads(prompt.split("SOURCE CUES:\n", 1)[1])
        if data[0]["cue"] == 0:
            return {"quotes": [{
                "quote": data[0]["text"],
                "cue_indices": [0],
            }]}
        return {"quotes": []}
    ledger, _windows = _extract(cues, chat)
    assert ledger["windows_without_quotes"] == []
    assert ledger["deterministic_fallback_windows"]
    assert ledger["source_cues_with_evidence"] >= 2
    assert all(
        any(index in group for item in ledger["accepted"]
            for index in item["cue_indices"])
        for group in make_windows(cues, max_chars=100)
    )


def test_independent_reviewer_wrong_shape_cannot_clear_semantic_review():
    source = _srt([
        "Ми говоримо про роботу з деревом.",
        "Ремісник пояснює техніку різьблення по дереву.",
    ])
    saved = {"id": ""}
    def chat(prompt):
        if "Extract up to three" in prompt:
            rows = json.loads(prompt.split("SOURCE CUES:\n", 1)[1])
            return {"quotes": [{
                "quote": row["text"], "cue_indices": [row["cue"]]
            } for row in rows]}
        if "Classify the main topics" in prompt:
            rows = json.loads(prompt.split("VERBATIM EVIDENCE:\n", 1)[1])
            saved["id"] = rows[0]["evidence_id"]
            return {"topics": [{
                "label_uk": "Різьблення по дереву",
                "evidence_ids": [row["evidence_id"] for row in rows],
            }]}
        if "You are an accurate" in prompt:
            evidence_id = saved["id"]
            return {
                "title": "Ремісник розповідає про роботу з деревом",
                "title_variants": ["Різьблення по дереву", "Техніка роботи з деревом",
                                   "Як працюють ремісники"],
                "description": "Ремісник описує роботу з деревом. " * 14,
                "tags": ["різьблення", "дерево", "майстри", "ремісник",
                         "техніка різьблення", "робота з деревом",
                         "майстер дерева", "дерев'яні вироби"],
                "support_ids": {
                    "title": [evidence_id],
                    "title_variants": [[evidence_id]] * 3,
                    "description": [evidence_id],
                    "tags": [[evidence_id]] * 8,
                },
            }
        raise AssertionError("Unexpected prompt")
    output = generate_universal_seo(
        source, chat, independent_review=lambda _prompt: {"unexpected": "yes"}
    )
    assert output["status"] == "REVIEW_REQUIRED"
    assert output["independent_review"]["review_status"] == "FAILED_CLOSED"
    assert output["publication_allowed"] is False


def test_citation_repair_only_updates_evidence_ids_not_content():
    from rg_youtube_control.seo_v2_pipeline import _repair_source_citations
    proof = [{
        "evidence_id": "ev_literal_1", "quote": "Ремісник працює з керамікою.",
        "cue_indices": [0], "start_ms": 0, "end_ms": 1000,
    }]
    draft = {
        "title": "Ремісник про кераміку",
        "title_variants": ["Кераміка у майстерні", "Як працює ремісник",
                           "Розмова про кераміку"],
        "description": "Ремісник розповідає про кераміку.",
        "tags": ["кераміка", "ремісник"],
        "support_ids": {"title": ["ev_literal_1"], "tags": []},
    }
    copy_before = {key: draft[key] for key in (
        "title", "title_variants", "description", "tags"
    )}
    def chat(prompt):
        if "You ONLY match existing Ukrainian search tags" in prompt:
            return {"tags": [["ev_literal_1"]] * 2}
        assert "source-citation matcher" in prompt
        return {"support_ids": {
            "title": ["ev_literal_1"],
            "description": ["ev_literal_1"],
            "title_variants": [["ev_literal_1"]] * 3,
            "tags": [["ev_literal_1"]] * 2,
        }}
    assert _repair_source_citations(draft, proof, chat) is True
    assert {key: draft[key] for key in copy_before} == copy_before
    assert len(draft["support_ids"]["tags"]) == 2


def test_citation_repair_rejects_forged_ids_without_loss_of_original():
    from rg_youtube_control.seo_v2_pipeline import _repair_source_citations
    proof = [{"evidence_id": "ev_1", "quote": "Точна цитата."}]
    draft = {
        "title": "Про матеріал", "title_variants": ["A", "B", "C"],
        "description": "Зміст", "tags": ["ключове слово"],
        "support_ids": {"title": ["ev_1"], "tags": []},
    }
    original = dict(draft["support_ids"])
    assert _repair_source_citations(
        draft, proof, lambda _: {"support_ids": {
            "title": ["ev_fake"], "description": ["ev_fake"],
            "title_variants": [["ev_fake"]] * 3,
            "tags": [["ev_fake"]],
        }}
    ) is False
    assert draft["support_ids"] == original


def test_writer_evidence_budget_covers_timelines_without_overflow():
    from rg_youtube_control.seo_v2_pipeline import _proof_index
    evidence = [{
        "evidence_id": f"ev_{i:04}",
        "quote": "Розмова про матеріали та інструменти " * 4,
        "start_ms": i * 1000,
        "end_ms": i * 1000 + 500,
        "cue_indices": [i],
    } for i in range(180)]
    topics = [{"label_uk": "Матеріали та інструменти",
               "evidence_ids": [item["evidence_id"] for item in evidence]}]
    selected = _proof_index(
        {"accepted": evidence}, topics, max_quotes=20, max_chars=6500
    )
    assert 2 <= len(selected) <= 20
    assert len(json.dumps(selected, ensure_ascii=False)) <= 6500
    selected_ids = {item["evidence_id"] for item in selected}
    assert "ev_0000" in selected_ids
    assert "ev_0179" in selected_ids


def test_writer_cannot_cite_valid_ledger_quote_absent_from_prompt():
    cues = parse_srt(_srt([
        "Майстер працює з деревом.",
        "Окремо говорили про архітектуру.",
    ]))
    ledger = evidence_ledger(cues, [
        {"quote": "Майстер працює з деревом.", "cue_indices": [0]},
        {"quote": "Окремо говорили про архітектуру.", "cue_indices": [1]},
    ])
    ids = [item["evidence_id"] for item in ledger["accepted"]]
    draft = {
        "title": "Майстер працює з деревом",
        "title_variants": ["Про дерево", "Робота майстра", "Майстерність"],
        "description": "Про роботу з деревом. " * 18,
        "tags": ["робота", "дерево", "майстер", "ремесло", "різьблення",
                 "інструменти", "техніка", "виробництво"],
        "support_ids": {
            "title": [ids[1]], "description": [ids[1]],
            "title_variants": [[ids[1]]] * 3,
            "tags": [[ids[1]]] * 8,
        },
    }
    gate = validate_draft(draft, ledger, cues, allowed_ids={ids[0]})
    assert "TITLE_UNSUPPORTED" in gate["issues"]
    assert "DESCRIPTION_UNSUPPORTED" in gate["issues"]
    assert gate["publication_allowed"] is False


def test_tag_only_repair_never_rewrites_other_fields():
    from rg_youtube_control.seo_v2_pipeline import _repair_source_citations
    proof = [{"evidence_id": "ev_11", "quote": "Майстер готує фарбу."}]
    draft = {
        "title": "Як майстер готує фарбу",
        "title_variants": ["Робота майстра", "Майстер і фарба", "Технологія фарби"],
        "description": "Майстер готує фарбу для роботи.",
        "tags": ["приготування фарби", "робота майстра"],
        "support_ids": {
            "title": ["ev_11"], "description": ["ev_11"],
            "title_variants": [["ev_11"]] * 3,
            "tags": [],
        },
    }
    before = {field: draft[field] for field in (
        "title", "title_variants", "description", "tags"
    )}
    prompts = []
    def chat(prompt):
        prompts.append(prompt)
        return {"tags": [["ev_11"], ["ev_11"]]}
    assert _repair_source_citations(draft, proof, chat) is True
    assert len(prompts) == 1
    assert "ONLY match existing" in prompts[0]
    assert all(draft[field] == before[field] for field in before)


def test_rejected_unselected_model_quote_is_an_audit_warning_not_seo_fact():
    cues = parse_srt(_srt(["Майстер розповідає про кераміку."]))
    ledger = evidence_ledger(cues, [
        {"quote": "Майстер розповідає про кераміку.", "cue_indices": [0]},
        {"quote": "Вигадана перемога на виборах.", "cue_indices": [0]},
    ])
    draft = {
        "title": "Майстер розповідає про кераміку",
        "title_variants": [
            "Кераміка в майстерні", "Як працює майстер",
            "Вироби з кераміки",
        ],
        "description": "Про кераміку та роботу майстра. " * 16,
        "tags": [
            "кераміка", "майстер", "вироби з кераміки",
            "робота майстра", "керамічні вироби", "ремесло",
            "виробництво", "розмова про кераміку",
        ],
    }
    eid = ledger["accepted"][0]["evidence_id"]
    draft["support_ids"] = {
        "title": [eid], "description": [eid],
        "title_variants": [[eid]] * 3, "tags": [[eid]] * 8,
    }
    result = validate_draft(draft, ledger, cues)
    assert "INVALID_QUOTE_PROPOSALS_DISCARDED" in result["extraction_warnings"]
    assert "NO_VERIFIED_SOURCE_QUOTES" not in result["issues"]
    assert result["semantic_review_required"] is True
    assert result["publication_allowed"] is False


def test_unusually_long_asr_caption_is_split_without_word_loss():
    words = [f"слово{i}" for i in range(900)]
    text = " ".join(words)
    srt = "1\n00:00:00,000 --> 00:00:20,000\n" + text + "\n"
    pieces = parse_srt(srt)
    assert len(pieces) > 1
    assert all(len(cue.text) <= 900 for cue in pieces)
    assert " ".join(cue.text for cue in pieces) == text
    assert all(cue.start_ms == 0 and cue.end_ms == 20000 for cue in pieces)
    assert [index for group in make_windows(pieces)
            for index in group] == list(range(len(pieces)))


def test_atomic_tag_and_citation_pairs_cannot_shift_by_index():
    from rg_youtube_control.seo_v2_pipeline import _draft
    proof = [
        {"evidence_id": "ev_wood", "quote": "Майстер працює з деревом."},
        {"evidence_id": "ev_metal", "quote": "Другий майстер кує метал."},
    ]
    def chat(_prompt):
        return {
            "title": "Ремесла та майстри",
            "title_variants": ["Майстри", "Дерево", "Метал"],
            "description": "Розмова про роботу майстрів.",
            "tag_evidence": [
                {"tag": "металеві вироби", "evidence_ids": ["ev_metal"]},
                {"tag": "робота з деревом", "evidence_ids": ["ev_wood"]},
                {"tag": "вигаданий сюжет", "evidence_ids": []},
            ],
            "support_ids": {
                "title": ["ev_wood"],
                "description": ["ev_wood"],
                "title_variants": [["ev_wood"]] * 3,
            },
        }
    result = _draft(
        [{"label_uk": "Ремесло", "evidence_ids": ["ev_wood", "ev_metal"]}],
        proof, chat,
    )
    assert result["tags"] == [
        "металеві вироби", "робота з деревом", "вигаданий сюжет",
    ]
    assert result["support_ids"]["tags"] == [
        ["ev_metal"], ["ev_wood"], [],
    ]
