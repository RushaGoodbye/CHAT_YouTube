import pytest
from rg_youtube_control.seo_source_cue_expansion import expand_source_cue_candidates


def row(text, start, duration=4):
    return {"text": text, "start": start, "duration": duration}


def block(index, start, end, verified=True):
    return {"index": index, "start": start, "end": end, "verified": verified}


def test_quote_is_exact_original_cue_not_stitched():
    rows = [row("Как дела у вас сегодня в этом городе?", 10),
            row("В соседнем городе люди обсуждают цены на автомобили.", 15)]
    result = expand_source_cue_candidates(rows, {"blocks": [block(1, 10, 20)]})
    assert {x["source_quote"] for x in result["evidence_candidates"]} == {r["text"] for r in rows}
    assert all(x["source_precision"] == "single_original_cue" for x in result["evidence_candidates"])
    assert all(not x["speaker_identified"] and not x["factual_truth_verified"] for x in result["evidence_candidates"])
    assert not result["publication_allowed"]


def test_unverified_windows_are_never_included():
    rows = [row("Люди обсуждают стоимость коммунальных услуг в городе.", 12),
            row("Собеседник сообщил о своих планах в ближайшее время.", 350)]
    result = expand_source_cue_candidates(rows, {"blocks": [block(1, 10, 50), block(2, 330, 380, False)]})
    assert result["unverified_block_ids"] == [2]
    assert not result["complete_timeline_verified"]
    assert all(x["block_index"] == 1 for x in result["evidence_candidates"])


def test_balanced_selection_covers_later_srt_windows():
    rows = [row(f"Обсуждали разные проблемы района номер {i} сегодня утром.", i * 2) for i in range(6)]
    rows += [row("Вопросы оплаты труда на заводе стали важными для жителей.", 320),
             row("В конце беседы обсуждали ремонт дорог и новых автобусов.", 630)]
    report = {"blocks": [block(1, 0, 30), block(2, 300, 390), block(3, 600, 690)]}
    result = expand_source_cue_candidates(rows, report, limit=3, per_window=3)
    assert {x["block_index"] for x in result["evidence_candidates"]} == {1, 2, 3}


def test_duplicate_cues_do_not_double_count():
    repeated = "На работе обсуждают задержку зарплаты за прошлый месяц."
    rows = [row(repeated, 1), row(repeated, 2),
            row("На дороге возле вокзала остановилось движение автобусов.", 3)]
    result = expand_source_cue_candidates(rows, {"blocks": [block(1, 0, 20)]}, limit=10)
    assert [x["source_quote"] for x in result["evidence_candidates"]].count(repeated) == 1


def test_empty_and_invalid_inputs_fail_closed():
    with pytest.raises(ValueError):
        expand_source_cue_candidates([], {"blocks": []})
    with pytest.raises(ValueError):
        expand_source_cue_candidates([], {"blocks": [block(1, 0, 10)]}, limit=0)
    result = expand_source_cue_candidates([row("Привет", 2)], {"blocks": [block(1, 0, 10)]})
    assert result["candidate_count"] == 0
    assert not result["publication_allowed"]


def test_invalid_timestamp_is_excluded():
    rows = [row("Эту цитату нельзя использовать с отрицательным временем.", -5),
            row("Эта фраза о работе сохранена с корректной временной меткой.", 42)]
    result = expand_source_cue_candidates(rows, {"blocks": [block(1, 0, 60)]})
    assert result["candidate_count"] == 1
    assert result["evidence_candidates"][0]["start_s"] == 42


def test_asr_fragment_is_not_mistaken_for_complete_statement():
    rows = [row("А сейчас я хочу сказать о результатах голосования", 15),
            row("Это конкретный факт, который озвучили в разговоре.", 32)]
    result = expand_source_cue_candidates(rows, {"blocks": [block(1, 0, 40)]})
    by_text = {x["source_quote"]: x for x in result["evidence_candidates"]}
    assert by_text[rows[0]["text"]]["may_be_incomplete"] is True
    assert by_text[rows[1]["text"]]["may_be_incomplete"] is False


def test_nonfinite_source_timestamps_not_trusted():
    rows = [row("Неверное время, фраза не должна быть доказательством.", float("inf")),
            row("Еще неверное время с бесконечной длительностью.", 20, float("inf")),
            row("Конкретная содержательная фраза с корректным временем.", 31)]
    result = expand_source_cue_candidates(rows, {"blocks": [block(1, 0, 100)]})
    assert result["candidate_count"] == 1
    assert result["evidence_candidates"][0]["start_s"] == 31


def test_diverse_candidate_gate_is_conservative():
    rows = [row("Ведущий обсуждал условия работы на крупном заводе.", 12),
            row("Работники затронули вопрос своевременной оплаты труда.", 15),
            row("Под конец разговор перешел на школьное образование.", 310)]
    report = {"blocks": [block(1, 0, 30), block(2, 300, 350)]}
    selected = expand_source_cue_candidates(rows, report)
    assert selected["candidate_count"] == 3
    assert selected["candidate_windows"] == [1, 2]
    assert selected["enough_diverse_candidates"]
    only_intro = expand_source_cue_candidates(rows[:2], report)
    assert not only_intro["enough_diverse_candidates"]
