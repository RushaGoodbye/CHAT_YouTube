from __future__ import annotations

import json

from rg_youtube_control.free_tools import (
    _extract_json_object,
    _video_id,
    parse_google_trends_csv_text,
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
