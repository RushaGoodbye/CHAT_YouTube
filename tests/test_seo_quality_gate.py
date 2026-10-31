from rg_youtube_control import free_tools
from rg_youtube_control.seo_quality_gate import inspect_package, language_error


def sample(**changes):
    value = {
        "title": "Шойгу: що говорять росіяни про кадрові зміни?",
        "title_variants": [
            "Шойгу та кадрові зміни: думки співрозмовників",
            "Чому обговорюють Шойгу в чат-рулетці?",
            "Що думають росіяни про рішення щодо Шойгу?",
        ],
        "description": "У чат-рулетці обговорюють кадрові зміни та роль Шойгу. "
        "Співрозмовники діляться своїми думками про події та сперечаються щодо їхніх причин. "
        "Ведучий ставить уточнювальні запитання, а учасники висловлюють різні погляди. "
        "Відео містить розмову та реакції на обговорювану тему.",
        "tags": ["Шойгу", "чат рулетка", "росіяни", "обговорення", "розмова", "кадрові зміни", "думки", "РАША ГУДБАЙ"],
    }
    value.update(changes)
    return value


def test_clean_ukrainian_package_is_format_ready_but_not_auto_publishable():
    result = inspect_package(sample())
    assert result["format_pass"]
    assert result["editorial_review_required"]
    assert result["problems"] == {}


def test_russian_legacy_title_is_detected_and_localized():
    result = inspect_package(sample(title="Увольнение Шойгу в России"))
    assert result["problems"]["title"] == ["NON_UKRAINIAN"]


def test_exact_field_diagnostics_and_duplicate_detection():
    result = inspect_package(sample(
        title_variants=["Шойгу і зміни"] * 3,
        tags=["Шойгу", "коррупция"],
    ))
    assert "DUPLICATE" in result["problems"]["title_variants"]
    assert "FEWER_THAN_EIGHT" in result["problems"]["tags"]
    assert "NON_UKRAINIAN" in result["problems"]["tags"]


def test_valid_ukrainian_words_are_not_rejected():
    assert not language_error("Росія та корупція: що кажуть росіяни?")
    assert language_error("Россия и коррупция: что говорят россияне?")


def test_generator_and_quality_gate_share_language_decisions():
    for sample_text in (
        "Росія та корупція: що кажуть росіяни?",
        "Шойгу: думки співрозмовників",
        "Россия и коррупция: что говорят россияне?",
        "Увольнение Шойгу в России",
    ):
        assert free_tools._seo_ukrainian_language_issue(sample_text) == language_error(sample_text)


def test_sanitizer_replaces_russian_variants_with_source_topic_questions():
    from rg_youtube_control.seo_quality_gate import sanitize_review_variants
    result, modified = sanitize_review_variants(
        "Шойгу: кадрові зміни",
        [
            "Шойгу и увольнение: почему?",
            "Шойгу: що кажуть співрозмовники?",
            "Почему говорят о коррупции?",
        ],
        [
            "Шойгу: про що говорять у чат-рулетці?",
            "Шойгу: погляди співрозмовників",
        ],
    )
    assert modified
    assert len(result) == 3
    assert all(not language_error(value) for value in result)


def test_sanitizer_never_fabricates_missing_grounded_alternatives():
    from rg_youtube_control.seo_quality_gate import sanitize_review_variants
    result, modified = sanitize_review_variants(
        "Кадрові зміни", ["Почему уволили?", "Що думають люди?"], []
    )
    assert modified
    assert result == ["Що думають люди?"]


def test_source_topic_fallback_ignores_unsupported_legacy_title():
    assert free_tools._grounded_review_title_variants(
        "Увольнение Шойгу в России", ""
    ) == []
    assert free_tools._grounded_review_title_variants(
        "Увольнение Шойгу в России", "Оценка своей жизни."
    ) == []


def test_source_topic_fallback_prioritizes_frequently_discussed_subject():
    titles = free_tools._grounded_review_title_variants(
        "Шойгу: що сталося?",
        ("Ми говоримо про Путіна та його рішення. " * 8)
        + "Також один раз згадали Шойгу.",
    )
    assert titles
    assert "Путін" in titles[0]
    assert "Шойгу" not in titles[0]
