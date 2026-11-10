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
