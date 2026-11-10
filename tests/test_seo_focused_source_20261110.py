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
