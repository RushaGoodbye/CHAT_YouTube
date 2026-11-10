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



def test_deterministic_tags_do_not_promote_title_only_subjects():
    from rg_youtube_control.free_tools import _grounded_tags_from_transcript
    tags = _grounded_tags_from_transcript(
        "Шойгу та мобілізація в Росії",
        "[00:01] Ми говоримо про місцеві ціни на продукти.",
    )
    assert "Шойгу" not in tags
    assert "мобілізація в Росії" not in tags



def test_deterministic_tags_reject_relationships_spread_across_dialogues():
    from rg_youtube_control.free_tools import _grounded_tags_from_transcript
    transcript = (
        "[00:10] Лукашенко розповів про Білорусь.\n"
        "[49:00] Говоримо про Україну.\n"
        "[55:00] Питання про зарплату в місті.\n"
    )
    tags = _grounded_tags_from_transcript("", transcript)
    assert "Білорусь і Україна" not in tags
    assert "РАША ГУДБАЙ" in tags
    assert "чат рулетка" in tags


def test_deterministic_tags_reject_unrelated_personnel_changes():
    from rg_youtube_control.free_tools import _grounded_tags_from_transcript
    transcript = (
        "[00:01] У цій розмові згадали Шойгу.\n"
        "[51:00] Інша людина обговорює звільнення працівників.\n"
    )
    tags = _grounded_tags_from_transcript("", transcript)
    assert "звільнення Шойгу" not in tags


def test_deterministic_tags_keep_exact_source_supported_phrase():
    from rg_youtube_control.free_tools import _grounded_tags_from_transcript
    transcript = "[00:01] Наше питання сьогодні — звільнення Шойгу."
    tags = _grounded_tags_from_transcript("", transcript)
    assert "звільнення Шойгу" in tags



def test_war_and_mobilization_title_cannot_override_unrelated_srt():
    from rg_youtube_control.free_tools import _grounded_tags_from_transcript
    tags = _grounded_tags_from_transcript(
        "Війна й мобілізація у Росії",
        "[00:01] Сьогодні говоримо про каву та приготування сніданку.",
    )
    assert "війна Росії проти України" not in tags
    assert "мобілізація в Росії" not in tags
