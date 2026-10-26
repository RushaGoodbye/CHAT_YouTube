"""The model can label a quote incorrectly; unclassified topics must not
discard every verified and operator-reviewable local SEO result."""
import pytest

from rg_youtube_control.free_tools import _deterministic_evidence_description


def test_real_operator_screenshot_topics_do_not_abort_seo():
    report = {
        "blocks": [
            {"verified": True, "topics": [{
                "topic": "Увольнение Шойгу: коррупция",
                "evidence": "Шойгу уволили из-за коррупции или всё идёт по плану",
            }]},
            {"verified": True, "topics": [{
                "topic": "Ідентифікація співрозмовників",
                "evidence": "Как тебя зовут и откуда ты приехал",
            }]},
            {"verified": True, "topics": [{
                "topic": "Поведінка в Росії та відносини між народами",
                "evidence": "Что ты думаешь о поведении людей в разных странах",
            }]},
            {"verified": True, "topics": [{
                "topic": "Критика поведінки в Дагестані через випадок з безплатною їдою",
                "evidence": "В Дагестане бесплатная еда в столовой и об этом спорили",
            }]},
        ]
    }
    review = []
    description = _deterministic_evidence_description(
        "Увольнение ШОЙГУ - коррупция или все идет по плану? | РАША ГУДБАЙ",
        report,
        review_notes=review,
    )
    assert "Шойгу" in description
    assert "Дагестані" in description
    assert "Ідентифікація" not in description
    assert any("Поведінка в Росії" in note for note in review)
    assert "Ідентифікація" not in " ".join(review)
    assert len(description) >= 260
    assert len(description) <= 950


def test_never_promote_llm_topic_when_quotation_does_not_support_it():
    report = {
        "blocks": [{
            "verified": True, "topics": [
                {
                    "topic": "Шойгу и уголовное дело о коррупции",
                    "evidence": "Сегодня я был в столовой и ел пирожки.",
                },
                {
                    "topic": "Стоимость бензина",
                    "evidence": "Сегодня бензин стал дороже в городе.",
                },
            ]
        }]
    }
    review = []
    result = _deterministic_evidence_description(
        "Шойгу и коррупция", report, review_notes=review,
    )
    assert "Шойгу" not in result
    assert "бензин" not in result.lower() or "ціни" in result
    assert review == ["Шойгу и уголовное дело о коррупции"]


def test_only_unrecognized_quotations_still_fail_closed():
    report = {
        "blocks": [{
            "verified": True, "topics": [{
                "topic": "Непідтверджена назва установи",
                "evidence": "У нас в деревне сегодня большая тишина",
            }]
        }]
    }
    notes = []
    result = _deterministic_evidence_description(
        "Вымышленный громкий скандал", report, review_notes=notes
    )
    assert "Вымышленный громкий скандал" not in result
    assert "Непідтверджена назва установи" not in result
    assert len(result) >= 260
    assert any("потрібен редакторський" in note for note in notes)


def test_missing_quotes_are_not_accepted_as_grounded():
    report = {
        "blocks": [{
            "verified": True, "topics": [{
                "topic": "Шойгу и коррупция",
                "evidence": "",
            }]
        }]
    }
    with pytest.raises(ValueError, match="No verified quotation"):
        _deterministic_evidence_description("Шойгу", report)


def test_generator_discloses_deferred_editorial_topics():
    from pathlib import Path
    source = Path("src/rg_youtube_control/free_tools.py").read_text(encoding="utf-8")
    generator = source.split("def generate_seo_package_local(", 1)[1]
    assert "review_notes=review_notes" in generator
    assert 'candidate["_evidence_editorial_review"] = review_notes' in generator
    assert '"evidence_editorial_review": list(' in generator
    assert '"Додаткові теми для редакційної перевірки: "' in generator
