from rg_youtube_control.free_tools import _tag_is_grounded


def test_rejects_tag_combining_unrelated_subtitle_topics():
    transcript = (
        "[00:01] Обговорюють мобілізацію та ставлення до неї.\n"
        "[48:10] Зовсім інша розмова про зарплати та пенсії.\n"
    )
    assert not _tag_is_grounded(
        "мобілізацію та зарплати", "", transcript
    )


def test_accepts_local_phrase_in_single_subtitle():
    transcript = "[00:01] Обговорюють мобілізацію та зарплати."
    assert _tag_is_grounded("мобілізацію та зарплати", "", transcript)


def test_preserves_project_format_tag():
    assert _tag_is_grounded("чат рулетка", "", "")
