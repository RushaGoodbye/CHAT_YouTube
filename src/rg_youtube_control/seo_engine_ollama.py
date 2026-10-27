"""Local Ollama structured JSON adapter for RG SEO Engine 1.0.

Reads local 127.0.0.1 only. No commercial API and no YouTube writes.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error

from .seo_engine_v1 import SeoDraft, generate_draft
from .seo_source_excerpt import select_source_excerpt


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
    # One bounded retry for transient local Ollama errors only. Never
    # retry malformed model content, and do not retry permanent HTTP 4xx.
    for attempt in range(2):
        try:
            with urllib.request.urlopen(
                req, timeout=timeout if attempt == 0 else min(timeout, 75.0)
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return str(payload["message"]["content"])
        except urllib.error.HTTPError as exc:
            if attempt or (exc.code < 500 and exc.code != 429):
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt:
                raise
    raise RuntimeError("Unreachable Ollama retry state")


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
        "\nЧАСТИ ОРИГИНАЛЬНОЙ РАСШИФРОВКИ ПО ВСЕМУ ВИДЕО: " +
        select_source_excerpt(current_title, transcript, char_budget=9000)
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



DESCRIPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "260–4500 characters, entirely Ukrainian language, no Russian paragraphs"
        },
    },
    "required": ["description"],
    "additionalProperties": False,
}


def ollama_description_json(*, current_title: str, transcript: str,
                            selected_title: str = "",
                            model: str = "qwen3:8b",
                            timeout: float = 100.0) -> dict:
    """Generate one replacement field only, keeping validated SEO fields."""
    prompt = (
        "Ти професійний український редактор YouTube. "
        "Відповідай ТІЛЬКИ JSON з полем description. "
        "НАПИШИ ПОВНІСТЮ УКРАЇНСЬКОЮ МОВОЮ без жодного російського речення. "
        "Створи конкретний SEO-опис на 450–1100 символів про основний сюжет "
        "цього відео, а не шаблон 'у тексті описано'. "
        "Не вигадуй прямих цитат, дат, фактів чи сторонніх подій. "
        "Російську мову оригіналу переклади українською, "
        "не копіюй російські фрази в опис. "
        "Заголовок оригіналу: " + current_title +
        "\nПеревірений заголовок майбутнього відео: " + selected_title +
        "\nПиши опис тільки за темою цього заголовка. "
        "\nРозшифровка (фрагменти з усього відео):\n" +
        select_source_excerpt(selected_title or current_title,
                              transcript, char_budget=11500)
    )
    body = json.dumps({
        "model": model, "stream": False, "format": DESCRIPTION_SCHEMA,
        "messages": [
            {"role": "system", "content": (
                "Пиши тільки українською мовою. Поле description "
                "має містити лише зв'язний український текст. JSON only."
            )},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.15},
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = json.loads(str(payload["message"]["content"]))
    if not isinstance(result, dict) or not isinstance(result.get("description"), str):
        raise ValueError("Description repair must return a description string")
    return result


def generate_with_ollama(*, video_id: str, current_title: str,
                         transcript: str, model: str = "qwen3:8b") -> SeoDraft:
    """Two full attempts, followed by at most two FIELD-ONLY repairs.

    The complete strict source, language, and topic gates are always rerun
    after repairs. No model-produced field is allowed to bypass validation.
    """
    latest_raw: str | None = None

    def first(prompt: str) -> str:
        nonlocal latest_raw
        latest_raw = ollama_json(prompt, model=model)
        return latest_raw

    try:
        return generate_draft(
            video_id=video_id, current_title=current_title,
            transcript=transcript, generate_json=first,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        # A mismatch is a SOURCE defect, not an output defect.
        if str(exc).startswith(("SOURCE_VIDEO_MISMATCH",
                                "Invalid YouTube Video ID",
                                "Transcript missing or too short")):
            raise

    def second(prompt: str) -> str:
        nonlocal latest_raw
        latest_raw = ollama_json(
            prompt + (
                "\nПРЕДЫДУЩИЙ ОТВЕТ НЕ ПРОШЁЛ ПРОВЕРКУ. "
                "Сформируй JSON заново. Все заголовки строго по-русски. "
                "Описание строго на УКРАИНСКОМ языке, полностью без "
                "русских предложений, 450–1100 символов, по главной теме "
                "исходного видео. Ровно 3 A/B-заголовка, 8–15 разных тегов, "
                "chapters = пустая строка. Нельзя выдумывать цитаты и события."
            ),
            model=model,
        )
        return latest_raw

    try:
        return generate_draft(
            video_id=video_id, current_title=current_title,
            transcript=transcript, generate_json=second,
        )
    except ValueError as exc:
        if str(exc).startswith(("SOURCE_VIDEO_MISMATCH",
                                "Invalid YouTube Video ID",
                                "Transcript missing or too short")):
            raise
        if latest_raw is None:
            raise

    # Preserve verified title/tags while repairing only the invalid field.
    # Two separate repairs are the upper bound: e.g. one title + one description.
    data = json.loads(latest_raw)
    if not isinstance(data, dict):
        raise ValueError("SEO response must be an object")
    def annotate_rejected_title(exc: ValueError) -> None:
        # A generated title is shareable for a PRIVATE read-only QA receipt;
        # never attach source captions, model payloads or local file paths.
        candidate = data.get("title")
        if isinstance(candidate, str):
            clean = " ".join(candidate.split())
            setattr(exc, "seo_rejected_title", clean[:110])

    used: set[str] = set()
    for _ in range(2):
        try:
            return generate_draft(
                video_id=video_id, current_title=current_title,
                transcript=transcript,
                generate_json=lambda _: json.dumps(data, ensure_ascii=False),
            )
        except ValueError as exc:
            last_exc = exc
            message = str(exc)
            if message.startswith(("Titles must be Russian",
                                    "Generic non-editorial headline",
                                    "Invalid primary title",
                                    "A/B titles are duplicates",
                                    "Exactly three valid A/B titles")) or (
                message.startswith("SEO_TOPIC_MISMATCH") and
                not message.startswith("SEO_TOPIC_MISMATCH: title and description")
            ):
                field = "titles"
            elif message.startswith(("Description must be Ukrainian",
                                      "Description length invalid",
                                      "SEO_TOPIC_MISMATCH: title and description")):
                field = "description"
            else:
                raise
            if field in used:
                annotate_rejected_title(exc)
                raise
            used.add(field)
            if field == "titles":
                fixed = ollama_titles_json(
                    current_title=current_title, transcript=transcript, model=model,
                )
                data["title"] = fixed.get("title")
                data["ab_titles"] = fixed.get("ab_titles")
            else:
                fixed = ollama_description_json(
                    current_title=current_title, selected_title=str(data.get("title") or ""),
                    transcript=transcript, model=model,
                )
                data["description"] = fixed["description"]
    # Re-run the whole gate after the second field-only repair.
    try:
        return generate_draft(
            video_id=video_id, current_title=current_title,
            transcript=transcript,
            generate_json=lambda _: json.dumps(data, ensure_ascii=False),
        )
    except ValueError as exc:
        annotate_rejected_title(exc)
        raise
