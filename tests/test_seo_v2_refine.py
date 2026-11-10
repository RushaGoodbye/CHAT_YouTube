"""SEO v2 focused repair never replaces a complete good SEO package."""
from rg_youtube_control.seo_v2_refine import repair_editorial_fields


PROOF = [{"evidence_id": "ev_1", "quote": (
    "Майстер описує роботу з деревом, техніку різьблення "
    "та підготовку інструментів."
)}]


def _draft():
    return {
        "title": "Техніка різьблення по дереву",
        "title_variants": [
            "Майстер розповідає про технологію обробки дерева "
            "та про роботу з різними інструментами у власній майстерні",
            "Що майстер розповів про різьблення по дереву, "
            "які інструменти підготував та як планує працювати з ними",
            "Різьблення по дереву та обробка матеріалів "
            "у майстерні з різними інструментами протягом дня",
        ],
        "description": "Майстер описує техніку різьблення по дереву. " * 7,
        "tags": ["різьблення по дереву", "робота майстра",
                 "дерев'яні вироби", "інструменти для дерева",
                 "обробка дерева", "майстерня", "техніка різьблення",
                 "підготовка інструментів"],
        "support_ids": {
            "title": ["ev_1"], "description": ["ev_1"],
            "title_variants": [["ev_1"]] * 3,
            "tags": [["ev_1"]] * 8,
        },
    }


def test_repair_only_fields_that_failed_format_or_editorial_gate():
    original = _draft()
    seen = []
    def model(prompt):
        seen.append(prompt)
        if "three A/B" in prompt:
            return {"variants": [
                {"text": "Майстер пояснює техніку різьблення по дереву",
                 "evidence_ids": ["ev_1"]},
                {"text": "Які інструменти потрібні для роботи з деревом",
                 "evidence_ids": ["ev_1"]},
                {"text": "Як підготувати інструменти для різьблення",
                 "evidence_ids": ["ev_1"]},
            ]}
        return {
            "description": (
                "Майстер розповідає про техніку різьблення по дереву. "
                "Він описує підготовку інструментів до початку роботи. "
                "Співрозмовник пояснює, як обробляє деревину. "
                "У розмові згадують різні способи роботи з матеріалом. "
                "Майстер також ділиться міркуваннями про власну майстерню. "
                "Він зосереджується на техніці підготовки й використання інструментів. "
                "Глядач дізнається, які етапи роботи назвав співрозмовник. "
            ),
            "evidence_ids": ["ev_1"],
        }
    repaired, fields = repair_editorial_fields(
        original, PROOF, model, spoken_numbers=set()
    )
    assert fields == ["title_variants", "description"]
    assert len(seen) == 2
    assert repaired["title"] == original["title"]
    assert repaired["tags"] == original["tags"]
    assert len(repaired["title_variants"]) == 3
    assert 400 <= len(repaired["description"]) <= 900


def test_repair_rejects_unsupported_numbers_and_source_ids():
    original = _draft()
    def model(prompt):
        if "three A/B" in prompt:
            return {"variants": [
                {"text": "Майстер підготував 9999 інструментів для роботи",
                 "evidence_ids": ["ev_1"]},
                {"text": "Робота з деревом у майстерні різьблення",
                 "evidence_ids": ["ev_1"]},
                {"text": "Обробка деревини та підготовка інструментів",
                 "evidence_ids": ["ev_1"]},
            ]}
        return {"description": "Певний текст. " * 35,
                "evidence_ids": ["ev_fake"]}
    result, changed = repair_editorial_fields(
        original, PROOF, model, spoken_numbers=set()
    )
    assert changed == []
    assert result == original
