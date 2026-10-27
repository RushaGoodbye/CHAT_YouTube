"""Local Ollama structured JSON adapter for RG SEO Engine 1.0.

Reads local 127.0.0.1 only. No commercial API and no YouTube writes.
"""
from __future__ import annotations

import json
import urllib.request

from .seo_engine_v1 import SeoDraft, generate_draft


SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Russian language only, concrete central news subject"},
        "ab_titles": {"type": "array", "minItems": 3, "maxItems": 3,
                      "items": {"type": "string", "description": "Russian language only, compelling specific topic"}},
        "description": {"type": "string", "description": "Ukrainian language only, full editorial description"},
        "tags": {"type": "array", "minItems": 8, "maxItems": 15,
                 "items": {"type": "string"}},
        "chapters": {"type": "string", "enum": [""]},
    },
    "required": ["title", "ab_titles", "description", "tags", "chapters"],
    "additionalProperties": False,
}


def ollama_json(prompt: str, *, model: str = "qwen3:8b",
                endpoint: str = "http://127.0.0.1:11434",
                timeout: float = 240.0) -> str:
    body = json.dumps({
        "model": model, "stream": False, "format": SCHEMA,
        "messages": [
            {"role": "system", "content": ("Return JSON only. All title and ab_titles strings "
             "MUST be in Russian. The description MUST be in Ukrainian. "
             "Never mix these languages. Use only transcript-grounded subjects.")},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.25},
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/api/chat", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return str(payload["message"]["content"])


TITLES_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "An engaging and concrete RUSSIAN title"},
        "ab_titles": {
            "type": "array", "minItems": 3, "maxItems": 3,
            "items": {"type": "string", "description": "RUSSIAN title only"},
        },
    },
    "required": ["title", "ab_titles"],
    "additionalProperties": False,
}


def ollama_titles_json(*, current_title: str, transcript: str,
                       model: str = "qwen3:8b", timeout: float = 75.0) -> dict:
    """One targeted RU-only headline repair without rewriting source-bound text."""
    prompt = (
        "Ты русский редактор YouTube. Отвечай строго JSON. "
        "Пиши title и три ab_titles ТОЛЬКО НА РУССКОМ языке. "
        "Не употребляй украинские слова или буквы і ї є ґ. "
        "Назови главный конкретный сюжет исходного ролика. "
        "Не начинай заголовки словами Диалог, Разговор, Обсуждение или Беседа. "
        "Не выдумывай темы, события, цитаты. "
        "Оригинальный заголовок: " + current_title +
        "\nФРАГМЕНТ ОРИГИНАЛЬНОЙ РАСШИФРОВКИ: " + transcript[:9000]
    )
    body = json.dumps({
        "model": model, "stream": False, "format": TITLES_SCHEMA,
        "messages": [
            {"role": "system", "content": "Russian title editor. JSON only; titles in Russian."},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.2},
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = json.loads(str(payload["message"]["content"]))
    if not isinstance(result, dict):
        raise ValueError("Title repair must return a JSON object")
    return result


def generate_with_ollama(*, video_id: str, current_title: str,
                         transcript: str, model: str = "qwen3:8b") -> SeoDraft:
    """Bounded model repair: one complete regeneration, then titles-only if needed."""
    latest_raw: str | None = None

    def original(prompt: str) -> str:
        nonlocal latest_raw
        latest_raw = ollama_json(prompt, model=model)
        return latest_raw

    try:
        return generate_draft(
            video_id=video_id, current_title=current_title,
            transcript=transcript, generate_json=original,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        if any(str(exc).startswith(prefix) for prefix in (
            "SOURCE_VIDEO_MISMATCH", "Invalid YouTube Video ID",
            "Transcript missing or too short",
        )):
            raise

    def one_repair(prompt: str) -> str:
        nonlocal latest_raw
        latest_raw = ollama_json(
            prompt + (
                "\nПРЕДЫДУЩИЙ ОТВЕТ НЕ ПРОШЁЛ ПРОВЕРКУ. "
                "Начни заново строго по JSON-схеме. "
                "Все title и ab_titles на русском без букв і ї є ґ. "
                "Не начинай название со слов Диалог, Разговор, Обсуждение. "
                "description целиком на украинском языке, 260–4500 символов. "
                "Нужны три уникальных A/B-заголовка и 8–15 уникальных тегов "
                "общей длиной до 500 символов. chapters = пустая строка. "
                "Не выдумывай факты и цитаты."
            ),
            model=model,
        )
        return latest_raw

    try:
        return generate_draft(
            video_id=video_id, current_title=current_title,
            transcript=transcript, generate_json=one_repair,
        )
    except ValueError as exc:
        if not str(exc).startswith(("Titles must be Russian",
                                    "Generic non-editorial headline")):
            raise
        # Only retry titles; preserve the description and tags already
        # generated. Never allow a model to bypass the final quality gate.
        if latest_raw is None:
            raise
        data = json.loads(latest_raw)
        if not isinstance(data, dict):
            raise
        fixed = ollama_titles_json(
            current_title=current_title, transcript=transcript, model=model,
        )
        data["title"] = fixed.get("title")
        data["ab_titles"] = fixed.get("ab_titles")
        return generate_draft(
            video_id=video_id, current_title=current_title,
            transcript=transcript,
            generate_json=lambda _: json.dumps(data, ensure_ascii=False),
        )
