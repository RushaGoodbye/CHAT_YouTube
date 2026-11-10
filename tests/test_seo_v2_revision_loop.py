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
