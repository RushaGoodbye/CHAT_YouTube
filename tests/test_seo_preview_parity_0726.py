"""Regression for the installed 0.7.23 deep SEO preview, not the offline Shoigu fixture."""
from rg_youtube_control.dialogue_seo import ab_title_issues

def test_gui_preview_generic_shoigu_ab_is_editorial_failure():
    variants = [
        "Почему уволили Шойгу? Коррупция или стратегия?",
        "Шойгу уволили по плану? Внутренние причины",
        "Увольнение Шойгу: дискуссия о причинах",
    ]
    issues = ab_title_issues(variants)
    assert issues, "The bad installed-window titles must not silently pass"
    assert any("надто загальний" in issue for issue in issues)

def test_distinct_specific_angles_do_not_trigger_generic_label():
    variants = [
        "Путин и Шойгу: почему говорили о хороших отношениях?",
        "Коррупция и обвинения: что рассказали о Шойгу?",
        "МЧС и война: что россиянин сказал о стратегии?",
    ]
    assert not any("надто загальний" in issue for issue in ab_title_issues(variants))

def test_gui_six_grounded_topics_not_silently_dropped():
    from rg_youtube_control.dialogue_seo import preserve_outline_topics
    source_topics = [
        ("причина увольнения Шойгу", "обсуждают причину увольнения Шойгу и кадровое решение"),
        ("корупція в російській армії", "коррупция и обвинения в министерстве обороны"),
        ("стратегічна неадекватність Шойгу", "война это война и нужен человек который стратегию"),
        ("дискусія про увільнення Шагу", "обсуждаем отставку шагу"),
        ("дискусія про причини зміни посади", "поменялся министр обороны после кадрового решения"),
        ("дискусія про корупцію та відповідальність", "коррупция и обвинения конкретным лицам"),
    ]
    report = {"blocks": [
        {"verified": True, "start_stamp": "00:00:00", "topics": [
            {"topic": topic, "evidence": quote}
            for topic, quote in source_topics[:3]
        ]},
        {"verified": True, "start_stamp": "00:05:03", "topics": [
            {"topic": topic, "evidence": quote}
            for topic, quote in source_topics[3:]
        ]},
    ]}
    description = (
        "У випуску співрозмовники обговорюють кадрові рішення в Міністерстві "
        "оборони РФ, корупційні припущення та військову компетентність Шойгу."
    )
    result, omitted = preserve_outline_topics(
        description, report, max_topic_bullets=50, max_body_bytes=3800
    )
    assert omitted == []
    assert "Шагу" not in result
    assert "корупц" in result.casefold()

def test_fresh_real_transcript_hallucinated_ab_titles_are_not_pass():
    variants = [
        "Коррупция и увольнение: шаги на пути правды",
        "Увольнение Шогу: по плану или нарушение?",
        "Ответ на вопрос: почему не ответили? | Дискуссия",
    ]
    issues = ab_title_issues(variants)
    assert any("помилку розпізнавання" in issue for issue in issues)
    assert any("загальною реплікою" in issue for issue in issues)
