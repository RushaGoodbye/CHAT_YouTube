"""Independent reviewer must see the actual source for a claimed SEO topic."""
from rg_youtube_control.seo_editorial_reviewer import (
    select_reviewer_notes_for_draft,
)


def _block(i: int, quote: str, inferred_topic: str = "Несуществующее событие"):
    return {
        "verified": True,
        "start_stamp": f"00:{i:02}:00",
        "topics": [{
            "topic": inferred_topic,
            "summary_uk": "Неправдивий модельний переказ",
            "evidence": quote,
        }],
    }


def test_reviewer_sees_source_for_short_topic_outside_evenly_spaced_sample():
    report = {"blocks": [
        _block(i, f"Погода сьогодні була теплою у місті номер {i}.")
        for i in range(60)
    ]}
    report["blocks"][17] = _block(
        17, "У Росії була мобілізація і люди боялися війни."
    )
    draft = {
        "title": "Росіянин розповів про мобілізацію",
        "title_variants": ["Чому люди бояться мобілізації?"],
        "description": "Обговорення мобілізації.",
        "tags": ["мобілізація", "чат рулетка"],
    }
    notes = select_reviewer_notes_for_draft(report, draft, max_notes=10)
    assert notes[0]["time"] == "00:17:00"
    assert notes[0]["quote"] == "У Росії була мобілізація і люди боялися війни."
    assert "00:00:00" in {note["time"] for note in notes}
    assert "00:59:00" in {note["time"] for note in notes}
    assert all("Неправдивий" not in str(note) for note in notes)


def test_reviewer_cannot_use_unverified_claim_even_if_title_matches():
    report = {"blocks": [
        {**_block(0, "Мобілізацію скасували назавжди."), "verified": False},
        _block(1, "Я працюю на заводі та ремонтую машини."),
    ]}
    notes = select_reviewer_notes_for_draft(
        report,
        {"title": "Мобілізацію скасували", "description": "", "tags": []},
        max_notes=10,
    )
    assert len(notes) == 1
    assert "скасували" not in notes[0]["quote"]


def test_reviewer_notes_empty_when_no_verbatim_sources():
    assert select_reviewer_notes_for_draft(
        {"blocks": [{"verified": False, "topics": []}]},
        {"title": "Назва"},
    ) == []
