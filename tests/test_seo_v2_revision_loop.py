"""Regressions for independently accepting semantic corrections per field."""
from rg_youtube_control.seo_v2_revision_loop import repair_fields_independently


PROOF = [{
    "evidence_id": "ev_1",
    "quote": "Співрозмовник сказав, що це може бути аудит.",
}, {
    "evidence_id": "ev_2",
    "quote": "Ведучий ставить питання про зміни в керівництві.",
}]


def test_good_title_repair_survives_unresolved_description_issue():
    current = {
        "title": "Доведена причина звільнення",
        "title_variants": ["Перше питання", "Друге питання", "Третє питання"],
        "description": "Аудит точно був причиною відставки.",
        "tags": ["аудит", "кадрові зміни"],
        "support_ids": {
            "title": ["ev_1"], "description": ["ev_1"],
            "title_variants": [["ev_1"]] * 3,
            "tags": [["ev_1"], ["ev_2"]],
        },
    }
    first_review = {"issues": [
        {"field": "title", "reason": "Unproven cause stated as fact"},
        {"field": "description", "reason": "Unproven cause stated as fact"},
    ]}
    def writer(prompt):
        if '"title"' in prompt.split("CURRENT DRAFT:", 1)[0]:
            return {"changes": {
                "title": "Співрозмовник припускає можливий аудит"
            }, "support_ids": {"title": ["ev_1"]}}
        return {"changes": {
            "description": "Аудит напевно був причиною."
        }, "support_ids": {"description": ["ev_1"]}}

    def reviewer(prompt):
        from json import loads
        candidate = loads(prompt.split("DRAFT:\n", 1)[1].split(
            "\nVERBATIM EVIDENCE:", 1
        )[0])
        issues = []
        if "Доведена" in candidate["title"]:
            issues.append({"field": "title", "reason": "Unproven certainty"})
        if "точно" in candidate["description"] or "напевно" in candidate["description"]:
            issues.append({"field": "description", "reason": "Unproven certainty"})
        return {"issues": issues}

    def gate(_candidate):
        return {"issues": []}

    result, _, review, changed = repair_fields_independently(
        current, PROOF, first_review, writer, reviewer, gate,
    )
    assert changed == ["title"]
    assert "припускає" in result["title"]
    assert result["description"] == current["description"]
    assert review["issues"][0]["field"] == "description"


def test_repair_must_never_change_untargeted_fields_or_add_source_errors():
    current = {
        "title": "Підтверджена причина",
        "title_variants": ["Перший", "Другий", "Третій"],
        "description": "Оригінал",
        "tags": ["аудит"],
        "support_ids": {
            "title": ["ev_1"], "title_variants": [["ev_1"]] * 3,
            "description": ["ev_1"], "tags": [["ev_1"]],
        },
    }
    def writer(_prompt):
        return {"changes": {
            "title": "Можливий аудит"
        }, "support_ids": {"title": ["ev_1"]}}
    def reviewer(_prompt):
        return {"issues": []}
    def gate(candidate):
        return {"issues": ["BAD_SOURCE"] if candidate["title"] != current["title"] else []}
    result, _, _, changed = repair_fields_independently(
        current, PROOF, {
            "issues": [{"field": "title", "reason": "Factual error"}],
        }, writer, reviewer, gate,
    )
    assert changed == []
    assert result == current


def test_bounded_second_attempt_removes_unverified_person_without_faking_name():
    proof = [
        {"evidence_id": "ev_role", "quote": "Говорили про звільнення керівника."},
        {"evidence_id": "ev_view", "quote": "Можливо, причина в аудиті."},
    ]
    current = {
        "title": "Чому звільнили Шайгурова: доведена причина",
        "title_variants": ["Погляд на події", "Причини звільнення", "Кадрові зміни"],
        "description": "Говорили про звільнення керівника.",
        "tags": ["кадрові зміни"],
        "support_ids": {
            "title": ["ev_role"], "description": ["ev_role"],
            "title_variants": [["ev_role"]] * 3,
            "tags": [["ev_role"]],
        },
    }
    proposals = iter([
        {"changes": {"title": "Можлива причина звільнення Шайгурова"},
         "support_ids": {"title": ["ev_role", "ev_view"]}},
        {"changes": {"title": "Чи пов'язане звільнення керівника з аудитом?"},
         "support_ids": {"title": ["ev_role", "ev_view"]}},
    ])
    seen = []
    def writer(prompt):
        seen.append(prompt)
        return next(proposals)
    def reviewer(_prompt):
        return {"issues": []}
    diagnostics = {}
    result, _, _, changed = repair_fields_independently(
        current, proof, {
            "issues": [{"field": "title", "reason": "Unverified name"}]
        }, writer, reviewer, lambda _: {"issues": []},
        diagnostics=diagnostics,
    )
    assert changed == ["title"]
    assert "Шайгурова" not in result["title"]
    assert len(seen) == 2
    assert diagnostics["title"] == ["UNVERIFIED_NAME_REMAINS", "ACCEPTED"]


def test_two_rejections_are_reported_and_never_marked_as_success():
    proof = [{"evidence_id": "ev_1", "quote": "Люди обговорюють правила."}]
    current = {
        "title": "Невідоме ім'я Шайгурова",
        "title_variants": ["A", "B", "C"], "description": "Розмова",
        "tags": ["правила"], "support_ids": {
            "title": ["ev_1"], "description": ["ev_1"],
            "title_variants": [["ev_1"]] * 3, "tags": [["ev_1"]],
        },
    }
    diagnostics = {}
    after, _, _, changed = repair_fields_independently(
        current, proof, {
            "issues": [{"field": "title", "reason": "Name not in SRT"}]
        }, lambda _: {"changes": {}, "support_ids": {}},
        lambda _: {"issues": []},
        lambda _: {"issues": []},
        diagnostics=diagnostics,
    )
    assert after == current
    assert changed == []
    assert diagnostics["title"] == [
        "NO_USABLE_FIELD_REVISION", "NO_USABLE_FIELD_REVISION"
    ]


def test_format_gate_initiates_tag_repair_even_when_reviewer_omits_tags():
    draft = {
        "title": "Розмова про підготовку інструментів",
        "title_variants": [
            "Які інструменти потрібні для роботи?",
            "Досвід майстра у виборі інструментів",
            "Практичні питання роботи з інструментами",
        ],
        "description": "Майстер обговорює інструменти. " * 15,
        "tags": ["інструменти", "майстер", "робота", "техніка", "поради"],
        "support_ids": {
            "title": ["ev_1"], "title_variants": [["ev_1"]] * 3,
            "description": ["ev_1"], "tags": [["ev_1"]] * 5,
        },
    }
    proof = [{"evidence_id": "ev_1",
              "quote": "Майстер обговорює інструменти для роботи."}]
    calls = []
    def writer(prompt):
        calls.append(prompt)
        assert "FEWER_THAN_EIGHT" in prompt
        return {"changes": {
            "tags": [
                "інструменти", "майстер", "робота", "техніка",
                "поради", "інструменти майстра", "робота з інструментами",
                "вибір інструментів",
            ]},
            "support_ids": {"tags": [["ev_1"]] * 8}}
    def gate(candidate):
        under = len(candidate["tags"]) < 8
        return {
            "issues": ["FORMAT_GATE_FAILED"] if under else [],
            "format": {"problems": {
                "tags": ["FEWER_THAN_EIGHT"] if under else []
            }},
            "editorial": {"issues": {}},
        }
    diagnostics = {}
    revised, result_gate, _, changed = repair_fields_independently(
        draft, proof, {"issues": []}, writer,
        lambda _: {"issues": []}, gate, diagnostics=diagnostics,
    )
    assert changed == ["tags"]
    assert len(revised["tags"]) == 8
    assert not result_gate["issues"]
    assert diagnostics["tags"] == ["ACCEPTED"]
    assert len(calls) == 1


def test_tag_edit_must_remove_original_count_error_before_accepting():
    draft = {
        "title": "Питання про освіту",
        "title_variants": ["Освіта", "Навчання", "Розмова"],
        "description": "Говорять про освіту.",
        "tags": ["освіта", "навчання"],
        "support_ids": {
            "title": ["ev_1"], "title_variants": [["ev_1"]] * 3,
            "description": ["ev_1"], "tags": [["ev_1"]] * 2,
        },
    }
    proof = [{"evidence_id": "ev_1", "quote": "Обговорюють освіту та навчання."}]
    def writer(_prompt):
        return {"changes": {
            "tags": ["освіта", "навчання", "школа"]
        }, "support_ids": {"tags": [["ev_1"]] * 3}}
    def gate(candidate):
        return {
            "issues": ["FORMAT_GATE_FAILED"],
            "format": {"problems": {"tags": ["FEWER_THAN_EIGHT"]}},
            "editorial": {"issues": {"tags": ["FEWER_THAN_EIGHT"]}},
        }
    diagnostics = {}
    result, _, _, changed = repair_fields_independently(
        draft, proof, {"issues": []}, writer, lambda _: {"issues": []},
        gate, diagnostics=diagnostics,
    )
    assert changed == []
    assert result == draft
    assert diagnostics["tags"] == [
        "FIELD_FORMAT_STILL_INVALID", "FIELD_FORMAT_STILL_INVALID"
    ]


def test_truthful_short_description_is_preserved_but_editorial_gate_stays_red():
    original = {
        "title": "Запитання про перевірку",
        "title_variants": ["Питання про аудит", "Думки щодо перевірки", "Розмова про події"],
        "description": "Аналіз довів, що аудит став встановленою причиною подій. " * 8,
        "tags": ["аудит"],
        "support_ids": {
            "title": ["ev_1"], "title_variants": [["ev_1"]] * 3,
            "description": ["ev_1"], "tags": [["ev_1"]],
        },
    }
    evidence = [{
        "evidence_id": "ev_1",
        "quote": "Можливо це аудит, але я не знаю точно.",
    }]
    safer = (
        "Співрозмовник припускає, що перевірка могла вплинути на ситуацію. "
        "Він не подає цю версію як доведений факт. "
        "У розмові йдеться саме про можливу причину, а не підтверджений висновок."
    )
    assert 160 <= len(safer) < 400
    def writer(_):
        return {"changes": {"description": safer},
                "support_ids": {"description": ["ev_1"]}}
    def critic(prompt):
        import json
        value = json.loads(prompt.split("DRAFT:\n", 1)[1].split(
            "\nVERBATIM EVIDENCE:", 1)[0])
        return {"issues": [] if value["description"] == safer else [
            {"field": "description", "reason": "Unsupported factual conclusion"}
        ]}
    def gate(candidate):
        too_short = len(candidate["description"]) < 400
        return {
            "issues": ["EDITORIAL_GATE_FAILED"] if too_short else [],
            "format": {"problems": {}},
            "editorial": {"issues": {
                "description": ["DESCRIPTION_UNDER_EDITORIAL_TARGET"]
            } if too_short else {}},
        }
    diag = {}
    draft, checked, _, changes = repair_fields_independently(
        original, evidence,
        {"issues": [{"field": "description", "reason": "Causality invented"}]},
        writer, critic, gate, diagnostics=diag,
    )
    assert changes == ["description"]
    assert draft["description"] == safer
    assert checked["issues"] == ["EDITORIAL_GATE_FAILED"]
    assert diag["description"] == ["SAFE_PARTIAL_REVIEW_REQUIRED"]


def test_shorter_description_is_not_retained_if_reviewer_disagrees():
    original = {
        "title": "Тема", "title_variants": ["A", "B", "C"],
        "description": "Аналіз доводить причину. " * 18,
        "tags": ["аудит"],
        "support_ids": {
            "title": ["ev_1"], "description": ["ev_1"],
            "title_variants": [["ev_1"]] * 3, "tags": [["ev_1"]],
        },
    }
    safe_text = "Обговорюють можливу причину перевірки. " * 6
    evidence = [{"evidence_id": "ev_1", "quote": "Можливо це була перевірка."}]
    def gate(obj):
        short = len(obj["description"]) < 400
        return {
            "issues": ["EDITORIAL_GATE_FAILED"] if short else [],
            "format": {"problems": {}},
            "editorial": {"issues": {"description": [
                "DESCRIPTION_UNDER_EDITORIAL_TARGET"
            ]} if short else {}},
        }
    result, _, _, changes = repair_fields_independently(
        original, evidence,
        {"issues": [{"field": "description", "reason": "Unverified claim"}]},
        lambda _: {"changes": {"description": safe_text},
                   "support_ids": {"description": ["ev_1"]}},
        lambda _: {"issues": [{"field": "description", "reason": "Still speculative"}]},
        gate,
    )
    assert result == original
    assert changes == []
