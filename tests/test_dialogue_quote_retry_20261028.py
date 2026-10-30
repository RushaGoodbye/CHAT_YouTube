"""Retry only invalid evidence; never promote nonverbatim model claims."""
import json

from rg_youtube_control.dialogue_seo import analyze_all_timeline_blocks


def _rows():
    return [{"text": "У розмові розповідали про бензин і ціни на заправках. "
             "Учасники повторювали запитання та знову поверталися до теми бензину і цін. "
             "Розмова продовжувалася без нових тверджень.",
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
    assert len(calls) == 3  # One final fixed-source quote rescue, no relaxed validation.


def test_rescues_exact_pinned_source_quote_after_two_model_failures():
    calls = []
    source_text = _rows()[0]["text"]

    def chat(*args, **kwargs):
        calls.append(args)
        if len(calls) <= 2:
            return '{"topics":[]}'
        # Third prompt pins one contiguous source quotation: the model
        # cannot invent or edit evidence, only propose a Ukrainian topic.
        prompt = args[0][1]["content"]
        assert "ДОСЛІВНИЙ evidence:" in prompt
        import re
        quoted = re.search(r"ДОСЛІВНИЙ evidence: (.+)$", prompt)
        evidence = json.loads(quoted.group(1))
        assert evidence in source_text
        return json.dumps({"topics": [{
            "topic": "Бензин",
            "summary_uk": "Співрозмовники говорять про бензин та ціни.",
            "evidence": evidence,
        }]}, ensure_ascii=False)

    result = analyze_all_timeline_blocks(_rows(), model="test", chat=chat)
    assert result["blocks_with_evidence"] == 1
    assert len(calls) == 3


def test_unverified_cache_does_not_prevent_fresh_source_check(tmp_path):
    from rg_youtube_control.dialogue_seo import _cache_file, split_timeline
    block = split_timeline(_rows())[0]
    path = _cache_file(tmp_path, block, "test")
    path.write_text('{"topics":[]}', encoding="utf-8")
    calls = []

    def chat(*args, **kwargs):
        calls.append(args)
        return json.dumps({"topics": [{
            "topic": "Бензин",
            "summary_uk": "Говорили про бензин і ціни на заправках.",
            "evidence": "У розмові розповідали про бензин і ціни на заправках",
        }]}, ensure_ascii=False)

    result = analyze_all_timeline_blocks(
        _rows(), model="test", chat=chat, cache_dir=tmp_path,
    )
    assert result["blocks_with_evidence"] == 1
    assert result["cache_hits"] == 0
    assert len(calls) == 1
