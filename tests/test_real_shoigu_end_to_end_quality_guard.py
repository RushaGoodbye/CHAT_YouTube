"""Real Shoigu 9:53 regression. No more one-off installer until this is green."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from rg_youtube_control.dialogue_seo import preserve_outline_topics
from rg_youtube_control.free_tools import (
    _grounded_chapters_from_transcript, _chapters_quality_error,
    transcript_sample_text,
)
from rg_youtube_control.ui import MainWindow


def _six_real_topics():
    titles = (
        "причина увольнения Шойгу",
        "корупція в російській армії",
        "стратегічна неадекватність Шойгу",
        "дискусія про увільнення Шагу",
        "дискусія про причини зміни посади",
        "дискусія про корупцію та відповідальність",
    )
    return {
        "blocks_total": 2,
        "blocks_with_evidence": 2,
        "rows_covered": 165,
        "blocks": [
            {"start_stamp": "00:00:00", "topics": [
                {"topic":t, "evidence":"джерело","summary_uk":t}
                for t in titles[:3]]},
            {"start_stamp": "00:05:03", "topics": [
                {"topic":t, "evidence":"джерело","summary_uk":t}
                for t in titles[3:]]},
        ],
    }


def test_all_six_shoigu_topics_are_preserved_without_arbitrary_two_topic_cap():
    report = _six_real_topics()
    synopsis = (
        "У цьому випуску чат-рулетки співрозмовники обговорюють "
        "перестановки в Міноборони РФ, можливі причини зміни посади "
        "Шойгу, корупційні звинувачення й стратегічну компетентність. "
    ) * 2
    from rg_youtube_control.dialogue_seo import _topic_display_uk
    title = "Увольнение ШОЙГУ - коррупция или все идет по плану?"
    result, omitted = preserve_outline_topics(
        synopsis, report, max_topic_bullets=12, max_body_bytes=3600,
        current_title=title,
    )
    assert not omitted
    for block in report["blocks"]:
        for topic in block["topics"]:
            # The evidence meaning must survive, but not Russian inflections
            # or misrecognized ASR names such as "Шагу".
            expected = _topic_display_uk(topic["topic"], title)
            assert expected in result
    assert "Шагу" not in result


def test_shoigu_chapter_fallback_does_not_emit_hardcoded_seven_chapters():
    # Only actual caption timestamp 00:00 and 05:03 are available.
    rows = [{"start":0,"text":"Всё идёт по плану"},
            {"start":303,"text":"Коррупция или всё идёт по плану"}]
    transcript = transcript_sample_text(rows)
    proposal = _grounded_chapters_from_transcript(
        current_title="Увольнение ШОЙГУ - коррупция или план?",
        transcript=transcript,
    )
    assert proposal == ""
    assert "08:11" not in proposal
    assert "Тимур Іванов" not in proposal
    assert _chapters_quality_error(
        "00:00 Початок розмови\n08:11 Тимур Іванов і команда Шойгу",
        transcript,
    ) != ""


def test_existing_rich_shoigu_draft_cannot_be_silently_replaced():
    reasons = MainWindow._seo_candidate_regressions(
        existing_description="Повний SEO-опис про Шойгу. " * 28,
        existing_chapters="\n".join(
            f"{n:02d}:00 Збережена глава {n}" for n in range(7)
        ),
        new_description="Короткий уривок про Шойгу.",
        new_chapters="",
        omitted_topics=["діалог про Міністерство", "питання фінансів"],
        ab_quality_issues=["повторюють один сюжетний гачок"],
    )
    assert len(reasons) >= 3
    assert any("7" in x for x in reasons)
    assert any("підтверджених тем" in x for x in reasons)
    assert any("A/B" in x for x in reasons)


def test_good_new_candidate_has_no_false_regressions():
    reasons = MainWindow._seo_candidate_regressions(
        existing_description="Стислий опис наявного відео.",
        existing_chapters="",
        new_description="Новий змістовний і перевірений опис відео.",
        new_chapters="",
        omitted_topics=[],
        ab_quality_issues=[],
    )
    assert reasons == []



def test_real_generic_ab_titles_from_live_qa_fail_editorial_quality():
    from rg_youtube_control.dialogue_seo import ab_title_issues

    weak = [
        "Почему уволили Шойгу? Коррупция или план?",
        "Шойгу уволили по плану? Видео с обсуждением",
        "Увольнение Шойгу: версии и мнения",
    ]
    reasons = ab_title_issues(weak)
    assert any("загальна фраза" in item and "2" in item for item in reasons)
    assert any("загальна фраза" in item and "3" in item for item in reasons)


def test_real_asr_name_and_russian_topic_normalize_without_new_names():
    from rg_youtube_control.dialogue_seo import _topic_display_uk
    title = "Увольнение ШОЙГУ - коррупция или все идет по плану? | РАША ГУДБАЙ"
    assert _topic_display_uk("дискусія про увільнення Шагу", title) == "звільнення Шойгу"
    assert _topic_display_uk("причина увольнения Шойгу", title) == "причина звільнення Шойгу"


def test_shoigu_shortened_primary_title_does_not_weaken_existing_hook():
    from rg_youtube_control.free_tools import _preserve_current_title_when_candidate_is_not_stronger
    existing = "Увольнение ШОЙГУ - коррупция или все идет по плану? | РАША ГУДБАЙ"
    weaker = "Увольнение Шойгу: коррупция или план?"
    assert _preserve_current_title_when_candidate_is_not_stronger(existing, weaker) == existing



def test_chapters_align_to_actual_evidence_quotes_not_hardcoded_times():
    from rg_youtube_control.dialogue_seo import grounded_chapters_from_evidence
    caption_lines = [
        (0, "Мы обсуждаем назначение в министерство обороны"),
        (15, "Говорим о новых решениях руководства"),
        (31, "На этой неделе обсуждали заявления"),
        (61, "Коррупция в министерстве обороны и ответственность"),
        (72, "Несколько собеседников спорят об обвинениях"),
        (93, "Почему решение о переводе министров вызывает споры"),
        (135, "Сейчас обсуждают стратегию российской армии и МЧС"),
        (147, "Участники называют разные причины"),
        (190, "Всё идёт по плану говорит следующий собеседник"),
        (220, "Он считает это кадровой перестановкой"),
        (250, "Финансовые вопросы и новый министр"),
        (290, "В конце возвращаются к теме ответственности"),
    ]
    original = "\n".join(
        f"[{n // 60:02d}:{n % 60:02d}] {line}"
        for n, line in caption_lines
    )
    report = {"blocks": [
        {"start_stamp":"00:00:00","end_stamp":"00:02:00",
         "topics":[{"topic":"корупція в міністерстві оборони",
                    "evidence":"Коррупция в министерстве обороны и ответственность"}]},
        {"start_stamp":"00:02:01","end_stamp":"00:05:00",
         "topics":[
            {"topic":"стратегія російської армії",
             "evidence":"Сейчас обсуждают стратегию российской армии и МЧС"},
            {"topic":"кадрова перестановка за планом",
             "evidence":"Он считает это кадровой перестановкой"},
         ]},
    ]}
    chapters = grounded_chapters_from_evidence(
        report, original, current_title="ШОЙГУ: корупція чи план?"
    )
    assert len(chapters.splitlines()) >= 3
    assert chapters.startswith("00:00 ")
    assert "08:11" not in chapters
    assert _chapters_quality_error(chapters, original) == ""
    assert "корупція" in chapters.casefold() or "стратегія" in chapters.casefold()



def test_review_generated_ukrainian_description_fixes_spoken_asr_errors():
    from rg_youtube_control.free_tools import _polish_generated_description
    original = (
        "Співрозмовники кажуть, що увільнення Шойгу могло бути плановим. "
        "Далі обговорюють корупцію та кадрові рішення в Міноборони."
    )
    fixed = _polish_generated_description(original)
    assert "увільнення" not in fixed
    assert "звільнення Шойгу" in fixed


def test_source_grounded_chapter_labels_are_not_duplicate_shoigu_story():
    from rg_youtube_control.dialogue_seo import grounded_chapters_from_evidence
    report = {
        "blocks": [
            {"start_stamp":"00:00:00","end_stamp":"00:02:30","topics":[
                {"topic":"причина звільнення Шойгу",
                 "evidence":"Говорили о причинах увольнения Шойгу и решениях Путина"},
                {"topic":"звільнення Шойгу",
                 "evidence":"Шойгу переназначили на другую должность"},
                {"topic":"корупція в російській армії",
                 "evidence":"Обсудили коррупцию в российской армии и расходы"},
            ]},
            {"start_stamp":"00:02:31","end_stamp":"00:05:30","topics":[
                {"topic":"стратегія російської армії",
                 "evidence":"Они спорили о стратегии российских войск"},
            ]},
        ]
    }
    rows = [
        (0,"Говорили о причинах увольнения Шойгу и решениях Путина"),
        (22,"Обсудили первые впечатления россиян"),
        (51,"Шойгу переназначили на другую должность"),
        (75,"Рассуждали о других кадровых перестановках"),
        (104,"Обсудили коррупцию в российской армии и расходы"),
        (130,"Перешли на другие вопросы"),
        (166,"Они спорили о стратегии российских войск"),
        (189,"Вопросы руководства остаются"),
        (210,"Обсуждение проблем обороны"),
        (250,"Мнения несколько различались"),
        (300,"Подвели предварительные итоги"),
    ]
    timed = "\n".join(f"[{s//60:02d}:{s%60:02d}] {t}" for s,t in rows)
    result = grounded_chapters_from_evidence(
        report,timed,current_title="Увольнение ШОЙГУ: коррупция или план?"
    )
    assert len(result.splitlines()) >= 3
    labels = [line.split(" ",1)[1] for line in result.splitlines()]
    assert labels.count("Звільнення Шойгу") + labels.count("Причина звільнення Шойгу") <= 1
    assert "Корупція в російській армії" in result



def test_ab_new_war_phase_claim_is_blocked_when_source_does_not_say_it():
    from rg_youtube_control.dialogue_seo import ab_title_issues
    report = {"blocks":[{"topics":[
        {"topic":"звільнення Шойгу та Путін",
         "summary_uk":"Думки про кадрову перестановку",
         "evidence":"Шойгу с Путиным хорошие отношения"},
        {"topic":"стратегія і МЧС",
         "summary_uk":"Розмова про армію",
         "evidence":"МЧС это МЧС А война это война и должен быть тот человек который стратегию"},
        {"topic":"корупція і план",
         "summary_uk":"Обговорення причин",
         "evidence":"Коррупция или Всё идёт по плану просто"},
    ]}]}
    variants=[
        "Шойгу и Путин: почему увольнение не испортило отношения",
        "Стратегия без Шойгу: как война переходит в новую фазу",
        "Коррупция или стратегия: что стоит за увольнением",
    ]
    issues=ab_title_issues(variants,report)
    assert any(
        "варіант 2" in item
        and ("непідтверджені" in item or "непідтверджений" in item)
        for item in issues
    )
