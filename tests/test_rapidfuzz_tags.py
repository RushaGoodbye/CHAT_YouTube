from rg_youtube_control.optimization import normalize_package_tags


def test_rapidfuzz_discards_only_strong_near_duplicate_tag_spellings():
    tags = [
        "чат-рулетка",
        "чат рулетка",
        "РАША ГУДБАЙ",
        "раша гудбай!",
        "россия",
        "россияне",
        "Путин",
        "путин и экономика",
        "война России против Украины",
        "экономика России",
    ]
    result = normalize_package_tags(tags)
    assert "чат-рулетка" in result
    assert "чат рулетка" not in result
    assert "РАША ГУДБАЙ" in result
    assert "раша гудбай!" not in result
    assert "россия" in result
    assert "россияне" in result
    assert "Путин" in result
    assert "путин и экономика" in result
    assert "война России против Украины" in result


def test_rapidfuzz_preserves_concrete_distinct_entities():
    result = normalize_package_tags([
        "Шойгу", "Белоусов", "Герасимов", "Пригожин",
        "зарплаты России", "пенсии России", "бензин России",
        "экономика России", "аресты России",
    ])
    assert len(result) == 9


def test_rapidfuzz_obeys_caps_without_erasing_specific_phrases():
    tags = [f"тема обсуждения {index}" for index in range(30)]
    result = normalize_package_tags(tags)
    assert 8 <= len(result) <= 15
    assert len(", ".join(result)) <= 500
    assert len({tag.casefold() for tag in result}) == len(result)
