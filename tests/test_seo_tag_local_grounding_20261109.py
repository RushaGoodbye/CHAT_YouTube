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



def test_title_alone_does_not_prove_topic_in_srt():
    title = "Мобілізація в Росії: пояснення"
    transcript = "[00:01] Люди обговорюють ціни на продукти."
    assert not _tag_is_grounded("мобілізація", title, transcript)


def test_title_is_fallback_only_when_no_srt_exists():
    assert _tag_is_grounded("мобілізація", "Говорять про мобілізація", "")
