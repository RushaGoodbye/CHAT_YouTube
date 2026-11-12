"""Evidence for generated SEO must never include LLM-inferred topic labels."""
from rg_youtube_control.dialogue_seo import evidence_outline_text
from rg_youtube_control.seo_editorial_reviewer import select_independent_source_notes


def test_evidence_prompt_uses_only_literal_srt_quotes():
    report = {"blocks": [{
        "verified": True, "start_stamp": "00:00:10",
        "topics": [{
            "topic": "Нібито перемога Росії",  # model inference; not evidence
            "summary_uk": "Росія перемогла у війні",  # hallucinated claim
            "evidence": "Я не знаю, що буде далі.",
        }],
    }]}
    prompt = evidence_outline_text(report)
    assert "Я не знаю, що буде далі." in prompt
    assert "Нібито перемога Росії" not in prompt
    assert "Росія перемогла у війні" not in prompt
    notes = select_independent_source_notes(report)
    assert notes == [{
        "time": "00:00:10", "quote": "Я не знаю, що буде далі.",
    }]


def test_unverified_block_never_becomes_confirmed_quote():
    report = {"blocks": [{
        "verified": False, "start_stamp": "00:03:40",
        "excerpt": "Нечіткий уривок",
        "topics": [{
            "topic": "Фейкова тема", "summary_uk": "Вигадка",
            "evidence": "Хибне твердження про подію",
        }],
    }]}
    assert "ДОСЛІВНА ЦИТАТА SRT" not in evidence_outline_text(report)
    assert select_independent_source_notes(report) == []
