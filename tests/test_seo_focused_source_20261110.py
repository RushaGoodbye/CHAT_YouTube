"""Focused SEO evidence uses source words, not model-inferred subjects."""
from rg_youtube_control.dialogue_seo import focused_literal_source_notes


def block(stamp, quote, topic="Вигадана перемога"):
    return {
        "verified": True,
        "start_stamp": stamp,
        "topics": [{
            "evidence": quote,
            "topic": topic,
            "summary_uk": "Непідтверджена подія",
        }],
    }


def test_description_evidence_prefers_title_topic_over_early_small_talk():
    report = {"blocks": [
        block("00:00:00", "Я працюю майстром і люблю ремонт автомобілів."),
        block("00:05:00", "У нас була мобілізація, люди не хотіли воювати."),
        block("00:10:00", "Мобілізація викликала питання про війну."),
        block("00:15:00", "Через мобілізацію багато людей сперечалися."),
    ]}
    notes = focused_literal_source_notes(
        report, "Росіянин про мобілізацію і війну", limit=3
    )
    assert len(notes) == 3
    assert all("мобілізац" in note["quote"].casefold() for note in notes)
    assert all("Вигадана перемога" not in str(note) for note in notes)


def test_sparse_source_never_invents_three_topics():
    report = {"blocks": [
        block("00:00:00", "Сьогодні ми говоримо про мобілізацію в Росії."),
    ]}
    notes = focused_literal_source_notes(
        report, "Мобілізація в Росії", limit=6,
    )
    assert len(notes) == 1
    assert "мобілізац" in notes[0]["quote"].casefold()


def test_unrelated_model_label_does_not_make_quote_relevant():
    report = {"blocks": [
        block("00:00:00", "Я обговорюю своє хобі та малювання.", topic="Мобілізація"),
        block("00:07:00", "Говорили про військову мобілізацію."),
    ]}
    notes = focused_literal_source_notes(report, "Мобілізація", limit=4)
    assert len(notes) == 1
    assert notes[0]["time"] == "00:07:00"


def test_unverified_quote_excluded_from_description_evidence():
    report = {"blocks": [
        {**block("00:00:00", "Мобілізацію скасували назавжди."), "verified": False},
        block("00:09:00", "Мобілізацію обговорюють росіяни."),
    ]}
    notes = focused_literal_source_notes(report, "Мобілізація")
    assert len(notes) == 1
    assert "скасували" not in notes[0]["quote"]


def test_unrelated_headline_does_not_select_random_evidence():
    report = {"blocks": [
        block("00:00:00", "Ми говорили про роботу на будівництві."),
        block("00:10:00", "Потім я розповів про погоду влітку."),
    ]}
    notes = focused_literal_source_notes(
        report, "Звільнення генерала і корупція в армії", limit=6,
    )
    assert notes == []


def test_title_relevance_handles_russian_source_ukrainian_headline():
    report = {"blocks": [
        block("00:00:00", "Я работаю мастером по ремонту квартир."),
        block("00:05:00", "Была мобилизация, и люди не хотели на войну."),
    ]}
    notes = focused_literal_source_notes(
        report, "Росіянин говорить про мобілізацію", limit=6,
    )
    assert len(notes) == 1
    assert notes[0]["time"] == "00:05:00"



def test_revision_notes_begin_with_critics_exact_source_quote():
    from rg_youtube_control.seo_editorial_reviewer import _targeted_repair_notes
    notes = [
        {"time": f"00:{i:02}:00", "quote": f"Дослівна репліка номер {i}."}
        for i in range(30)
    ]
    issues = [{
        "field": "description",
        "reason": "Непідтверджене тлумачення",
        "evidence": '00:23:00: "Дослівна репліка номер 23."',
    }]
    selected = _targeted_repair_notes(notes, issues, limit=8)
    assert selected[0]["time"] == "00:23:00"
    assert len(selected) == 8
    assert selected[0]["quote"] == notes[23]["quote"]


def test_revision_notes_without_critic_evidence_cover_timeline():
    from rg_youtube_control.seo_editorial_reviewer import _targeted_repair_notes
    notes = [{"time": str(i), "quote": f"Слова номер {i}"} for i in range(50)]
    selected = _targeted_repair_notes(notes, [], limit=10)
    assert len(selected) == 10
    assert selected[0] == notes[0]
    assert selected[-1] == notes[-1]



def test_offtopic_headline_is_rebuilt_using_only_literal_source_notes():
    import json
    from rg_youtube_control.free_tools import _repair_offtopic_headline
    report = {"blocks": [
        block("00:01:00", "В Росії була мобілізація, багато людей не хотіли воювати."),
        block("00:05:00", "Люди обговорювали мобілізацію та війну."),
    ]}
    calls = []
    def chat(messages, **_kwargs):
        calls.append(messages[-1]["content"])
        return json.dumps({
            "title": "Росіянин про мобілізацію: чому люди не хотіли воювати?"
        }, ensure_ascii=False)
    title, repaired = _repair_offtopic_headline(
        "Звільнення невідомого генерала через корупцію",
        report, model="test", timeout=1.0, chat=chat,
    )
    assert repaired is True
    assert "мобілізацію" in title
    assert len(calls) == 1
    assert "Вигадана перемога" not in calls[0]
    assert "Непідтверджена подія" not in calls[0]


def test_offtopic_repair_rejects_new_invented_headline():
    import json
    from rg_youtube_control.free_tools import _repair_offtopic_headline
    report = {"blocks": [
        block("00:04:00", "Поговорили про роботу та вихідні."),
    ]}
    original = "Розмова про санкції та вибори"
    title, repaired = _repair_offtopic_headline(
        original, report, model="test", timeout=1.0,
        chat=lambda *_a, **_k: json.dumps({
            "title": "Невідомий генерал переміг на виборах"
        }, ensure_ascii=False),
    )
    assert repaired is False
    assert title == original


def test_grounded_headline_needs_no_extra_model_call():
    from rg_youtube_control.free_tools import _repair_offtopic_headline
    report = {"blocks": [block("00:01:00", "Говорили про мобілізацію та війну.")]}
    title, changed = _repair_offtopic_headline(
        "Розмова про мобілізацію", report, model="test", timeout=1.0,
        chat=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("Grounded title must not trigger extra inference")
        ),
    )
    assert changed is False
    assert title == "Розмова про мобілізацію"


def test_single_generic_overlap_does_not_prove_invented_combined_headline():
    report = {"blocks": [
        block("00:03:00", "Учасник говорив про війну."),
        block("00:08:00", "Я не знаю, що буде завтра."),
    ]}
    assert focused_literal_source_notes(
        report, "Війна та перемога на виборах", limit=3,
    ) == []


def test_reporting_verb_does_not_block_real_topic_with_russian_source():
    report = {"blocks": [
        block("00:03:00", "Была мобилизация, многие люди не хотели воевать."),
    ]}
    notes = focused_literal_source_notes(
        report, "Росіянин говорить про мобілізацію", limit=3,
    )
    assert len(notes) == 1
    assert notes[0]["time"] == "00:03:00"


def test_focused_description_source_excludes_peripheral_first_nine_blocks():
    report = {"blocks": [
        block(f"00:{i:02}:00", f"Я працюю в магазині та обговорюю свій графік {i}.")
        for i in range(9)
    ] + [
        block("00:10:00", "Люди сперечалися через мобілізацію."),
        block("00:11:00", "Мобілізація вплинула на розмови про війну."),
    ]}
    notes = focused_literal_source_notes(
        report, "Мобілізація та війна", limit=9,
    )
    assert len(notes) == 2
    assert all("магазині" not in note["quote"] for note in notes)
