"""Rank only verifiable quotation words; preserve all important source spans."""
from rg_youtube_control.dialogue_seo import (
    evidence_outline_text,
    rank_literal_evidence,
)
from rg_youtube_control.free_tools import _ab_distinct_evidence_brief


def _block(time, evidence, *, topic="Модель вигадала іншу тему", summary="Непідтверджений підсумок"):
    return {
        "verified": True,
        "start_stamp": time,
        "topics": [{
            "topic": topic,
            "summary_uk": summary,
            "evidence": evidence,
        }],
    }


def test_repeated_srt_subject_outweighs_unrelated_one_off_quote():
    report = {"blocks": [
        _block("00:00:00", "Мені подобається моя робота у майстерні."),
        _block("00:04:00", "У нас була мобілізація, багато людей не хотіли воювати."),
        _block("00:08:00", "Я говорив про мобілізацію і людей, які бояться війни."),
        _block("00:12:00", "Мобілізація стала темою нашої суперечки."),
    ]}
    ranked = rank_literal_evidence(report)
    assert ranked[0]["start_stamp"] != "00:00:00"
    assert "мобілізац" in ranked[0]["evidence"].casefold()
    assert len(ranked) == 4


def test_source_outline_keeps_recurring_subject_and_timeline_edges_when_capped():
    subjects = (
        "археологія астрономія ботаніка геологія океанографія "
        "математика хімія геометрія каліграфія реставрація "
        "філософія метеорологія скульптура живопис фотографія "
        "література музикознавство лінгвістика картографія "
        "геодезія металургія електроніка біологія орнітологія"
    ).split()
    report = {"blocks": [
        _block(f"00:{i:02}:00", f"{word} {word} {word}.")
        for i, word in enumerate(subjects)
    ]}
    report["blocks"][9]["topics"][0]["evidence"] = "Мобілізація зачепила багато людей у нашому місті."
    report["blocks"][15]["topics"][0]["evidence"] = "Люди часто згадують мобілізацію та її наслідки."
    output = evidence_outline_text(report, max_chars=1200)
    assert "00:00:00" in output
    assert "00:23:00" in output
    assert "00:09:00" in output
    assert "00:15:00" in output
    assert "Модель вигадала іншу тему" not in output
    assert "Непідтверджений підсумок" not in output


def test_ab_brief_does_not_promote_model_topic_labels_to_evidence():
    report = {"blocks": [
        _block("00:01:00", "Вони сперечалися про роботу та зарплату."),
        _block("00:07:00", "Ми говорили про військову мобілізацію."),
        _block("00:12:00", "Мобілізація викликала питання про війну."),
    ]}
    brief = _ab_distinct_evidence_brief(report)
    assert "ДОСЛІВНА ЦИТАТА SRT" in brief
    assert "Модель вигадала іншу тему" not in brief
    assert "Непідтверджений підсумок" not in brief



def test_recurrence_survives_near_duplicate_display_quote_deduplication():
    report = {"blocks": [
        _block("00:00:00", "Археологія цікава наука про минуле людства."),
        _block("00:02:00", "Мобілізація у Росії вплинула на людей."),
        _block("00:05:00", "Мобілізація у Росії вплинула на людей."),
        _block("00:08:00", "Мобілізація у Росії вплинула на людей."),
    ]}
    ranked = rank_literal_evidence(report)
    assert len(ranked) == 2
    assert ranked[0]["evidence"] == "Мобілізація у Росії вплинула на людей."
