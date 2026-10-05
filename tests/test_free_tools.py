from __future__ import annotations

import json

from rg_youtube_control.free_tools import (
    _extract_json_object,
    _video_id,
    parse_google_trends_csv_text,
    summarize_google_trends,
    transcript_text,
)


def test_video_id_from_common_urls() -> None:
    assert _video_id("abcDEF123_-") == "abcDEF123_-"
    assert _video_id("https://www.youtube.com/watch?v=abcDEF123_-") == "abcDEF123_-"
    assert _video_id("https://youtu.be/abcDEF123_-") == "abcDEF123_-"
    assert _video_id("https://www.youtube.com/shorts/abcDEF123_-") == "abcDEF123_-"


def test_extract_json_from_fenced_model_response() -> None:
    result = _extract_json_object(
        """```json
        {"title":"Тест","description":"Опис","tags":["a"]}
        ```"""
    )
    assert result["title"] == "Тест"


def test_transcript_text_has_timestamps_and_limit() -> None:
    rows = [
        {"text": "Перша репліка", "start": 0, "duration": 1.5},
        {"text": "Друга репліка", "start": 65, "duration": 2},
    ]
    value = transcript_text(rows)
    assert "[00:00] Перша репліка" in value
    assert "[01:05] Друга репліка" in value


def test_parse_google_trends_csv() -> None:
    rows = parse_google_trends_csv_text(
        "Категорія: Усі категорії\n\nДата,бензин,Путін\n2026-10-01,65,40\n"
    )
    assert rows == [{"Дата": "2026-10-01", "бензин": "65", "Путін": "40"}]


def test_summarize_google_trends_orders_by_latest_interest() -> None:
    rows = [
        {"Дата": "2026-10-01", "бензин": "40", "Путін": "60"},
        {"Дата": "2026-10-02", "бензин": "90", "Путін": "50"},
    ]
    summary = summarize_google_trends(rows)
    assert summary[0]["term"] == "бензин"
    assert summary[0]["latest"] == 90.0
    assert summary[0]["average"] == 65.0


def test_transcript_sample_text_covers_full_video():
    from rg_youtube_control.free_tools import transcript_sample_text

    rows = [
        {"text": f"line {index}", "start": index * 60, "duration": 5}
        for index in range(60)
    ]
    sampled = transcript_sample_text(rows, max_chars=300, segments=6)

    assert "[00:00]" in sampled
    assert "[59:00]" in sampled
    assert "[...]" in sampled
    assert len(sampled) <= 300


def test_recover_missing_description_uses_plain_text_fallback(monkeypatch) -> None:
    import rg_youtube_control.free_tools as ft

    long_text = (
        "У відео співрозмовник відповідає на запитання про зміни у своєму житті "
        "та оцінює події через власний досвід. Він пояснює, які проблеми помічає "
        "у повсякденності, що вважає важливим і з чим не погоджується. "
        "Розмова переходить до конкретних прикладів, реакцій на запитання ведучого "
        "та аргументів самого співрозмовника. Окремо звучать оцінки ситуації в Росії "
        "і ставлення до подій, які обговорюються під час діалогу."
    )
    replies = iter([
        '{"description":"Коротко."}',
        '{"description":"Ще надто коротко."}',
        long_text,
    ])

    def fake_chat(*_args, **_kwargs):
        return next(replies)

    monkeypatch.setattr(ft, "ollama_chat", fake_chat)
    result = ft._recover_missing_description(
        current_title="Тестова назва",
        transcript="[00:00] тест " * 200,
        public_context={},
        model="qwen3:8b",
    )

    assert len(result) >= 320
    assert result.startswith("У відео")


def test_description_quality_rejects_raw_transcript_dump() -> None:
    from rg_youtube_control.free_tools import _description_quality_error

    transcript = (
        "Тяжелее стало цены поднялись в принципе всё что было так есть просто "
        "цены поднялись немножко ну ясно что кто-то должен это оплачивать "
        "вот оплачиваем ценами конечно вы довольны ну да у всего своя цена "
        "поверьте это ещё не всё вам долго расплачиваться "
    ) * 12
    description = transcript[:1800]

    assert _description_quality_error(description, transcript) in {
        "too_long",
        "not_summary_prose",
        "wrong_language",
        "transcript_copy",
    }


def test_description_quality_accepts_ukrainian_summary() -> None:
    from rg_youtube_control.free_tools import _description_quality_error

    transcript = (
        "Тяжелее стало цены поднялись зарплата изменилась люди отвечают "
        "как изменилась жизнь за год и оценивают ситуацию в России "
    ) * 40
    description = (
        "У цьому випуску росіяни відповідають, як змінилося їхнє життя за 2023 рік. "
        "Співрозмовники говорять про зростання цін, зарплати, пенсії та власний добробут. "
        "Частина учасників стверджує, що живе краще, інші прямо кажуть про погіршення. "
        "Окремо звучать оцінки економіки Росії та ставлення до політики влади. "
        "Розмова показує різні, часто суперечливі відповіді на одне просте запитання."
    )

    assert _description_quality_error(description, transcript) == ""


def test_grounded_description_uses_detected_topics_without_transcript_dump() -> None:
    from rg_youtube_control.free_tools import (
        _description_quality_error,
        _grounded_description_from_transcript,
    )

    transcript = (
        "[00:00] цены поднялись и стало дороже жить\n"
        "[01:00] зарплата поднялась\n"
        "[02:00] мне добавили пенсию\n"
        "[03:00] экономика улучшается\n"
        "[04:00] 90 процентов будут голосовать за Путина\n"
    ) * 12
    description = _grounded_description_from_transcript(
        "Как улучшилась жизнь россиян за прошедший 2023 год? | РАША ГУДБАЙ",
        transcript,
    )

    assert "ціни та вартість життя" in description
    assert "зарплати та доходи" in description
    assert "пенсії та соціальні виплати" in description
    assert "економіка Росії" in description
    assert "цены поднялись" not in description
    assert "Опис побудовано" not in description
    assert "Дивіться повну розмову" in description
    assert _description_quality_error(description, transcript) == ""
