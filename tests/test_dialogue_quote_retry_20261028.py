"""Retry only invalid evidence; never promote nonverbatim model claims."""
import json

from rg_youtube_control.dialogue_seo import analyze_all_timeline_blocks


def _rows():
    return [{"text": "У розмові розповідали про бензин і ціни на заправках",
             "start": 0.0, "duration": 12.0}]


def test_retries_unverified_model_excerpt_once_with_exact_quote():
    calls = []

    def chat(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            return json.dumps({"topics": [{"topic": "Бензин", 
                "summary_uk": "Говорили про бензин на заправках.",
                "evidence": "Слів, яких немає в оригінальному фрагменті"}]})
        return json.dumps({"topics": [{"topic": "Бензин",
            "summary_uk": "Розмова про бензин і ціни на заправках.",
            "evidence": "У розмові розповідали про бензин і ціни на заправках"}]})

    result = analyze_all_timeline_blocks(_rows(), model="test", chat=chat)
    assert result["blocks_total"] == result["blocks_with_evidence"] == 1
    assert len(calls) == 2


def test_rejects_nonverbatim_evidence_even_after_retry():
    calls = []

    def chat(*args, **kwargs):
        calls.append(args)
        return json.dumps({"topics": [{"topic": "Корупція",
            "summary_uk": "Непідтверджена вигадана подія в регіоні.",
            "evidence": "Корупція, вибухи, відставка і звільнення"}]})

    result = analyze_all_timeline_blocks(_rows(), model="test", chat=chat)
    assert result["blocks_with_evidence"] == 0
    assert result["unverified_blocks"] == [1]
    assert len(calls) == 1  # Too-short fragment: do not waste retries.
