"""Local Ollama structured JSON adapter for RG SEO Engine 1.0.

Reads local 127.0.0.1 only. No commercial API and no YouTube writes.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error

from .seo_engine_v1 import SeoDraft, generate_draft, _valid_ukrainian_description
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
        "Верни 1 основной заголовок и ровно 3 A/B-заголовка: "
        "№1 — конкретный факт или утверждение, №2 — вопрос по той же "
        "теме, №3 — реакция или противопоставление по той же теме. "
        "Проверяй, что все четыре строки различаются после удаления "
        "регистра и пробелов. НЕЛЬЗЯ повторять один вариант дважды. "
        "Каждый заголовок до 100 символов. "
        "Не употребляй украинские слова или буквы і ї є ґ. "
        "Не используй пустые вводные фразы «Обсуждение роли», "
        "«Чат рулетка о», «Разговор на тему». "
        "Если заголовок о благодарности Путину, в названии нужна "
        "именно благодарность, а не общее обсуждение политики. "
        "Если заголовок про «Храм Пятёрочки», сохрани оба имени. "
        "Если заголовок про похороны друзей и молчание, сохрани "
        "именно эти обстоятельства. "
        "ОБЯЗАТЕЛЬНО сохрани центральных героев и главную тему "
        "ОРИГИНАЛЬНОГО ЗАГОЛОВКА во всех четырёх вариантах. "
        "Не подменяй исходную историю случайным эпизодом из субтитров: "
        "рыбак и джедай не превращаются в разговор о грибах. "
        "Заголовок должен передавать тот же смысл, но может использовать "
        "проверенные синонимы (не менять = без изменений). "
        "Назови главный конкретный сюжет исходного ролика. "
        "Не начинай заголовки словами Диалог, Разговор, Обсуждение или Беседа. "
        "Не выдумывай темы, события, цитаты. "
        "Оригинальный заголовок: " + current_title +
        "\nЧАСТИ ОРИГИНАЛЬНОЙ РАСШИФРОВКИ ПО ВСЕМУ ВИДЕО: " +
        select_source_excerpt(current_title, transcript, char_budget=6500)
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
        "Створи конкретний SEO-опис на 450–1100 символів "
        "ТІЛЬКИ ПРО СЮЖЕТ ЗАТВЕРДЖЕНОГО ЗАГОЛОВКА. "
        "Сторонні репліки, другорядні теми, політика та військові технології "
        "не повинні витісняти головних героїв із заголовка. "
        "Кожний абзац опису повинен стосуватися головної теми. "
        "Не пиши шаблон 'у тексті описано' або 'можливо, з підкаста'. "
        "Не вигадуй прямих цитат, дат, фактів чи сторонніх подій. "
        "Російську мову оригіналу переклади українською, "
        "не копіюй російські фрази в опис. "
        "Заголовок оригіналу: " + current_title +
        "\nПеревірений заголовок майбутнього відео: " + selected_title +
        "\nПиши опис тільки за темою цього заголовка. "
        "\nРозшифровка (фрагменти з усього відео):\n" +
        select_source_excerpt(selected_title or current_title,
                              transcript, char_budget=6500) +
        "\\n\\nУВАГА: ПИШИ ВИКЛЮЧНО ПРО ТЕМУ ЗАТВЕРДЖЕНОГО ЗАГОЛОВКА "
        "І ТІЛЬКИ УКРАЇНСЬКОЮ МОВОЮ."
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
    if _valid_ukrainian_description(result["description"]):
        return result
    # Translating a first-pass draft is easier for the local 8B model than
    # generating Ukrainian from thousands of Russian transcript words.
    # One bounded retry; all topic and quality checks still run afterward.
    translated_prompt = (
        "Ти перекладач і редактор української мови. "
        "Відповідай JSON {description: ...} і НІЧОГО БІЛЬШЕ. "
        "Перепиши наведений текст ПОВНІСТЮ УКРАЇНСЬКОЮ МОВОЮ. "
        "Усі слова та речення мають бути українськими, не залишай "
        "російських службових слів 'что', 'которые', 'обсуждение', "
        "'события', 'в России'. Збережи тему та факти, не додавай нових. "
        "Від 450 до 1100 символів. "
        "\\nТЕМА: " + (selected_title or current_title) +
        "\\nТЕКСТ ДЛЯ УКРАЇНСЬКОГО ПЕРЕКЛАДУ:\\n" +
        result["description"][:2000] +
        "\\n\\nНАПИШИ ВИКЛЮЧНО УКРАЇНСЬКОЮ МОВОЮ."
    )
    retry_body = json.dumps({
        "model": model, "stream": False, "format": DESCRIPTION_SCHEMA,
        "messages": [
            {"role": "system", "content": (
                "Тільки українська мова. Ти перекладач. Ніколи не відповідай російською."
            )},
            {"role": "user", "content": translated_prompt},
        ],
        "options": {"temperature": 0.1},
    }, ensure_ascii=False).encode("utf-8")
    retry_req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat", data=retry_body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(retry_req, timeout=min(timeout, 75.0)) as response:
        translated = json.loads(response.read().decode("utf-8"))
    candidate = json.loads(str(translated["message"]["content"]))
    if not isinstance(candidate, dict) or not isinstance(candidate.get("description"), str):
        raise ValueError("Description translation must be an object")
    if not _valid_ukrainian_description(candidate["description"]):
        raise ValueError("Description must be Ukrainian")
    return candidate


TAGS_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array", "minItems": 8, "maxItems": 15,
            "items": {"type": "string", "description": "Useful specific searchable keyword"},
        },
    },
    "required": ["tags"],
    "additionalProperties": False,
}


def ollama_topic_tags_json(*, selected_title: str, current_title: str,
                           transcript: str, model: str = "qwen3:8b",
                           timeout: float = 80.0) -> dict:
    """Regenerate off-topic tags once from the approved source-backed title."""
    prompt = (
        "Ты специалист SEO для YouTube. Верни только JSON поле tags. "
        "Создай от 8 до 15 РАЗНЫХ коротких поисковых тегов для ролика. "
        "ОБЯЗАТЕЛЬНО хотя бы 5 тегов ДОЛЖНЫ отражать существительные "
        "и именованные предметы ИМЕННО ПОДТВЕРЖДЁННОГО ЗАГОЛОВКА. "
        "Откажись от любых слов из случайных побочных тем видео, "
        "даже если они встречаются в длинной беседе. "
        "Не придумывай факты. Допускаются РАША ГУДБАЙ и чат рулетка, "
        "но они НЕ ЗАМЕНЯЮТ тематические ключевые слова. "
        "Суммарная длина тегов менее 500 символов. "
        "\\nПОДТВЕРЖДЕННЫЙ ЗАГОЛОВОК: " + selected_title +
        "\\nИСХОДНЫЙ ЗАГОЛОВОК: " + current_title +
        "\\nФРАГМЕНТЫ РАСШИФРОВКИ: " +
        select_source_excerpt(selected_title, transcript, char_budget=6500)
    )
    body = json.dumps({
        "model": model, "stream": False, "format": TAGS_SCHEMA,
        "messages": [
            {"role": "system", "content":
             "Return JSON only. Tags must reflect the exact video's main title."},
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
    data = json.loads(str(payload["message"]["content"]))
    if not isinstance(data, dict) or not isinstance(data.get("tags"), list):
        raise ValueError("Tags repair must return list")
    return data


def _restore_one_ab_from_verified_original(data: dict, current_title: str) -> None:
    """Recover one duplicate A/B title with the already source-verified title.

    This does NOT invent a new topic. The full editorial and source gates
    still validate the repaired package after this fallback.
    """
    variants = data.get("ab_titles")
    main = str(data.get("title") or "").strip()
    original = " ".join(str(current_title or "").split())
    if not isinstance(variants, list) or len(variants) != 3:
        return
    if not original or len(original) > 100 or any(
        ch in "іїєґ" for ch in original.casefold()
    ):
        return
    clean: list[str] = []
    seen = {main.casefold()}
    for value in variants:
        if not isinstance(value, str) or not value.strip():
            return
        candidate = " ".join(value.split())
        if len(candidate) > 100:
            return
        if candidate.casefold() not in seen:
            seen.add(candidate.casefold())
            clean.append(candidate)
    if len(clean) == 2 and original.casefold() not in seen:
        data["ab_titles"] = [*clean, original]


def generate_with_ollama(*, video_id: str, current_title: str,
                         transcript: str, model: str = "qwen3:8b") -> SeoDraft:
    """Two full attempts, followed by at most three FIELD-ONLY repairs.

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
    # At most three separate repairs: titles, description and subject tags.
    data = json.loads(latest_raw)
    if not isinstance(data, dict):
        raise ValueError("SEO response must be an object")
    _restore_one_ab_from_verified_original(data, current_title)
    def annotate_rejected_title(exc: ValueError) -> None:
        # A generated title is shareable for a PRIVATE read-only QA receipt;
        # never attach source captions, model payloads or local file paths.
        candidate = data.get("title")
        if isinstance(candidate, str):
            clean = " ".join(candidate.split())
            setattr(exc, "seo_rejected_title", clean[:110])
        variants = data.get("ab_titles")
        if isinstance(variants, list):
            setattr(exc, "seo_rejected_ab_count", len(variants))
            setattr(exc, "seo_rejected_ab_unique", len({
                str(v).strip().casefold() for v in variants
            }))
        desc = data.get("description")
        if isinstance(desc, str):
            lowered = desc.casefold()
            setattr(exc, "seo_ua_letter_count",
                    sum(ch in "іїєґ" for ch in lowered))
            setattr(exc, "seo_ru_letter_count",
                    sum(ch in "ыъэё" for ch in lowered))


    used: set[str] = set()
    for _ in range(3):
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
                                      "Generic AI meta-description forbidden",
                                      "SEO_TOPIC_MISMATCH: title and description")):
                field = "description"
            elif message.startswith("SEO_TAGS_TOPIC_MISMATCH"):
                field = "tags"
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
                _restore_one_ab_from_verified_original(data, current_title)
            elif field == "description":
                fixed = ollama_description_json(
                    current_title=current_title,
                    selected_title=str(data.get("title") or ""),
                    transcript=transcript, model=model,
                )
                data["description"] = fixed["description"]
            else:
                fixed = ollama_topic_tags_json(
                    current_title=current_title,
                    selected_title=str(data.get("title") or ""),
                    transcript=transcript, model=model,
                )
                data["tags"] = fixed["tags"]
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
