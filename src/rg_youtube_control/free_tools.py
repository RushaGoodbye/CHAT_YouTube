from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:8b"


@dataclass(frozen=True)
class ToolProbe:
    name: str
    available: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _video_url(value: str) -> str:
    value = (value or "").strip()
    if value.startswith(("http://", "https://")):
        return value
    return f"https://www.youtube.com/watch?v={value}"


def _video_id(value: str) -> str:
    value = (value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", value):
        return value
    match = re.search(
        r"(?:v=|youtu\.be/|shorts/|live/)([A-Za-z0-9_-]{6,20})",
        value,
    )
    if not match:
        raise ValueError("Не вдалося визначити YouTube video_id.")
    return match.group(1)


def _extract_json_object(text: str) -> dict[str, Any]:
    value = (text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^\s*```(?:json)?\s*", "", value, flags=re.I)
        value = re.sub(r"\s*```\s*$", "", value)
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Локальна модель не повернула JSON.")
        payload = json.loads(value[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Очікувався JSON-об'єкт.")
    return payload


def probe_free_tools(
    *,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    ollama_model: str = DEFAULT_OLLAMA_MODEL,
    timeout: float = 1.5,
) -> dict[str, dict[str, Any]]:
    probes: dict[str, ToolProbe] = {}

    try:
        import yt_dlp  # type: ignore

        probes["yt_dlp"] = ToolProbe(
            "yt-dlp", True, str(getattr(yt_dlp.version, "__version__", "installed"))
        )
    except Exception:
        executable = shutil.which("yt-dlp")
        probes["yt_dlp"] = ToolProbe(
            "yt-dlp", bool(executable), executable or "не встановлено"
        )

    try:
        import youtube_transcript_api  # type: ignore

        probes["transcript"] = ToolProbe(
            "youtube-transcript-api",
            True,
            str(getattr(youtube_transcript_api, "__version__", "installed")),
        )
    except Exception:
        probes["transcript"] = ToolProbe(
            "youtube-transcript-api", False, "не встановлено"
        )

    try:
        req = urllib.request.Request(
            f"{ollama_url.rstrip('/')}/api/tags",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = [
            str(item.get("name") or item.get("model") or "")
            for item in payload.get("models", [])
            if isinstance(item, dict)
        ]
        normalized = {item.split(":latest")[0] for item in models}
        model_ready = (
            ollama_model in models
            or ollama_model.split(":latest")[0] in normalized
        )
        detail = (
            f"{ollama_model} готова"
            if model_ready
            else "Ollama працює, модель ще не завантажена"
        )
        probes["ollama"] = ToolProbe("Ollama", True, detail)
        probes["ollama_model"] = ToolProbe(ollama_model, model_ready, detail)
    except Exception as exc:
        probes["ollama"] = ToolProbe("Ollama", False, str(exc)[:160])
        probes["ollama_model"] = ToolProbe(
            ollama_model, False, "сервер Ollama недоступний"
        )

    return {key: value.to_dict() for key, value in probes.items()}


def fetch_public_metadata(video: str) -> dict[str, Any]:
    """Read public YouTube page metadata without YouTube Data API quota."""
    try:
        import yt_dlp  # type: ignore
    except Exception as exc:
        raise RuntimeError("yt-dlp не встановлено.") from exc

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(_video_url(video), download=False)

    return {
        "video_id": str(info.get("id") or _video_id(video)),
        "title": str(info.get("title") or ""),
        "description": str(info.get("description") or ""),
        "tags": [str(item) for item in (info.get("tags") or [])],
        "duration": int(info.get("duration") or 0),
        "channel": str(info.get("channel") or info.get("uploader") or ""),
        "channel_id": str(info.get("channel_id") or ""),
        "upload_date": str(info.get("upload_date") or ""),
        "view_count": int(info.get("view_count") or 0),
        "like_count": int(info.get("like_count") or 0),
        "webpage_url": str(info.get("webpage_url") or _video_url(video)),
        "automatic_captions": sorted((info.get("automatic_captions") or {}).keys()),
        "subtitles": sorted((info.get("subtitles") or {}).keys()),
        "source": "yt-dlp",
        "youtube_data_api_quota": 0,
    }


def fetch_transcript(
    video: str,
    languages: Iterable[str] = ("uk", "ru", "en"),
) -> list[dict[str, Any]]:
    """Fetch an available YouTube transcript without YouTube Data API quota."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
    except Exception as exc:
        raise RuntimeError("youtube-transcript-api не встановлено.") from exc

    api = YouTubeTranscriptApi()
    transcript = api.fetch(_video_id(video), languages=list(languages))
    rows = transcript.to_raw_data()
    return [
        {
            "text": str(item.get("text") or ""),
            "start": float(item.get("start") or 0.0),
            "duration": float(item.get("duration") or 0.0),
        }
        for item in rows
    ]


def transcript_text(
    rows: Iterable[dict[str, Any]],
    *,
    max_chars: int = 24000,
) -> str:
    parts: list[str] = []
    used = 0
    for item in rows:
        text = " ".join(str(item.get("text") or "").split())
        if not text:
            continue
        start = max(0, int(float(item.get("start") or 0)))
        stamp = f"{start // 60:02d}:{start % 60:02d}"
        line = f"[{stamp}] {text}"
        if used + len(line) + 1 > max_chars:
            break
        parts.append(line)
        used += len(line) + 1
    return "\n".join(parts)


def transcript_sample_text(
    rows: Iterable[dict[str, Any]],
    *,
    max_chars: int = 12000,
    segments: int = 6,
) -> str:
    """Build a timestamped sample spread across the whole video."""
    prepared: list[tuple[int, str]] = []
    for item in rows:
        text = " ".join(str(item.get("text") or "").split())
        if not text:
            continue
        start = max(0, int(float(item.get("start") or 0)))
        stamp = f"{start // 60:02d}:{start % 60:02d}"
        prepared.append((start, f"[{stamp}] {text}"))

    if not prepared:
        return ""

    full = "\n".join(line for _start, line in prepared)
    if len(full) <= max_chars:
        return full

    segments = max(2, int(segments))
    separator = "\n[...]\n"
    separator_budget = len(separator) * (segments - 1)
    usable = max(200, max_chars - separator_budget)
    per_window = max(20, usable // segments)
    last_start = prepared[-1][0]

    chunks: list[str] = []
    globally_used: set[int] = set()

    for segment in range(segments):
        target = last_start * segment / (segments - 1)
        center = min(
            range(len(prepared)),
            key=lambda index: abs(prepared[index][0] - target),
        )

        left = center
        right = center + 1
        chosen: list[int] = []
        used = 0
        while left >= 0 or right < len(prepared):
            candidates: list[int] = []
            if left >= 0:
                candidates.append(left)
            if right < len(prepared):
                candidates.append(right)
            if not candidates:
                break
            pick = min(
                candidates,
                key=lambda index: abs(prepared[index][0] - target),
            )
            if pick == left:
                left -= 1
            else:
                right += 1
            if pick in globally_used:
                continue
            line_len = len(prepared[pick][1]) + (1 if chosen else 0)
            if chosen and used + line_len > per_window:
                break
            if not chosen and line_len > per_window:
                chosen.append(pick)
                globally_used.add(pick)
                break
            chosen.append(pick)
            globally_used.add(pick)
            used += line_len

        if chosen:
            chunk = "\n".join(prepared[index][1] for index in sorted(chosen))
            chunks.append(chunk)

    result = separator.join(chunks)
    if len(result) <= max_chars:
        return result

    # Preserve the first and last sampled windows. If a very long caption made
    # the result exceed the budget, reduce middle windows first.
    while len(result) > max_chars and len(chunks) > 2:
        middle = len(chunks) // 2
        lines = chunks[middle].splitlines()
        if len(lines) > 1:
            chunks[middle] = "\n".join(lines[:-1])
        else:
            chunks.pop(middle)
        result = separator.join(chunk for chunk in chunks if chunk)

    if len(result) <= max_chars:
        return result

    # Last-resort trimming keeps the first line of the first window and the
    # last line of the final window intact.
    first_lines = chunks[0].splitlines() if chunks else []
    last_lines = chunks[-1].splitlines() if chunks else []
    first_anchor = first_lines[0] if first_lines else ""
    last_anchor = last_lines[-1] if last_lines else ""
    anchors = separator.join(
        item for item in (first_anchor, last_anchor) if item
    )
    return anchors[:max_chars]


def ollama_chat(
    messages: list[dict[str, str]],
    *,
    model: str = DEFAULT_OLLAMA_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    timeout: float = 300.0,
    temperature: float = 0.2,
    json_mode: bool = False,
) -> str:
    request_payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": temperature},
    }
    if json_mode:
        request_payload["format"] = "json"
    body = json.dumps(
        request_payload,
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{ollama_url.rstrip('/')}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama недоступна: {exc}") from exc
    message = payload.get("message") or {}
    text = str(message.get("content") or "").strip()
    if not text:
        raise RuntimeError("Ollama повернула порожню відповідь.")
    return text



def _normalize_seo_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Accept common local-model key aliases, then normalize to our schema."""
    normalized = dict(candidate or {})
    aliases = {
        "title": ("title", "new_title", "назва", "name"),
        "description": (
            "description", "full_description", "description_uk",
            "опис", "повний_опис", "summary",
        ),
        "tags": ("tags", "теги", "keywords", "key_words"),
        "chapters": ("chapters", "розділи", "sections", "timestamps"),
        "title_variants": (
            "title_variants", "titleVariants", "variants",
            "варіанти_назви", "назви",
        ),
    }
    for canonical, keys in aliases.items():
        if normalized.get(canonical) not in (None, "", []):
            continue
        for key in keys:
            value = candidate.get(key)
            if value not in (None, "", []):
                normalized[canonical] = value
                break
    return normalized


def _recover_missing_description(
    *,
    current_title: str,
    transcript: str,
    public_context: dict[str, Any],
    model: str,
) -> str:
    """Focused zero-quota recovery for missing or too-thin descriptions."""
    if not transcript.strip():
        return ""

    last = ""
    for attempt in range(2):
        prompt = f"""
Створи ЛИШЕ український опис YouTube-відео за транскриптом.
Не вигадуй фактів. Не використовуй старий опис як джерело фактів.
Довжина: 450-850 символів. Потрібно щонайменше 320 символів.
Перші 1-2 речення конкретно пояснюють, що відбувається у відео.
Далі коротко назви 2-4 реальні теми або тези, які прямо є в транскрипті.
Не додавай посилання, хештеги, ENGLISH SUMMARY, заголовок чи службові фрази.
Не пиши загальні фрази типу "обговорюються важливі теми".
Поверни JSON рівно такого формату:
{{"description":"..."}}

ПОТОЧНА НАЗВА:
{current_title}

ПУБЛІЧНИЙ КОНТЕКСТ:
{json.dumps(public_context or {}, ensure_ascii=False)[:2500]}

ТРАНСКРИПТ:
{transcript[:12000]}
""".strip()
        if attempt:
            prompt += (
                "\n\nПОПЕРЕДНЯ ВІДПОВІДЬ БУЛА ЗАКОРОТКОЮ. "
                "Напиши повний змістовний опис 450-850 символів."
            )
        raw = ollama_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Ти точний редактор YouTube. "
                        "Поверни тільки JSON з одним ключем description."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            model=model,
            temperature=0.05,
            json_mode=True,
        )
        recovered = _normalize_seo_candidate(_extract_json_object(raw))
        last = str(recovered.get("description") or "").strip()
        if len(last) >= 320:
            return last
    return last


def _recover_title_variants(
    *,
    current_title: str,
    transcript: str,
    model: str,
) -> list[str]:
    """Focused recovery of exactly three distinct Russian title variants."""
    prompt = f"""
Створи РІВНО 3 різні варіанти назви YouTube-відео російською.
Кожна до 100 символів. Лише факти та теми, підтверджені транскриптом.
Без вигаданих цитат і без непідтвердженого клікбейту.
Поверни JSON:
{{"title_variants":["...","...","..."]}}

ПОТОЧНА НАЗВА:
{current_title}

ТРАНСКРИПТ:
{transcript[:8000]}
""".strip()
    raw = ollama_chat(
        [
            {
                "role": "system",
                "content": "Поверни тільки JSON з ключем title_variants.",
            },
            {"role": "user", "content": prompt},
        ],
        model=model,
        temperature=0.08,
        json_mode=True,
    )
    recovered = _normalize_seo_candidate(_extract_json_object(raw))
    return [
        str(item).strip()
        for item in (recovered.get("title_variants") or [])
        if str(item).strip()
    ][:3]


def generate_seo_package_local(
    *,
    current_title: str,
    current_description: str = "",
    current_tags: list[str] | None = None,
    transcript: str = "",
    public_context: dict[str, Any] | None = None,
    is_short: bool = False,
    model: str = DEFAULT_OLLAMA_MODEL,
) -> dict[str, Any]:
    context = public_context or {}
    prompt = f"""
Ти редактор YouTube-проєкту «РАША ГУДБАЙ». Підготуй SEO-пакет без вигадування фактів.
Використовуй ТІЛЬКИ наведений контекст. Якщо факту немає в контексті - не додавай його.

Правила:
- основна назва та РІВНО 3 різні A/B варіанти назви: російською;
- кожна назва до 100 символів, конкретна, зрозуміла і прив'язана до реальної теми відео;
- не копіюй поточну назву без SEO-покращення, якщо транскрипт дає точніший сильний хук;
- опис: українською, 350-900 символів змістовного тексту до службових посилань;
- перші 1-2 речення мають конкретно пояснювати, що відбувається у відео;
- усі твердження про зарплати, економіку, соціальні гарантії, інфраструктуру, втрати, перемоги, санкції, ціни та інші факти дозволені ЛИШЕ якщо вони прямо підтверджені транскриптом або наданим контекстом;
- якщо транскрипт суперечить старому опису, довіряй транскрипту;
- старий опис використовуй лише як технічний контекст, а не як джерело фактів;
- не пиши загальні рекламні фрази на кшталт «обговорюються основні теми», якщо можеш назвати конкретні теми з транскрипту;
- не додавай ENGLISH SUMMARY, англомовний дубль або переклад опису;
- без клікбейту, який не підтверджується контекстом;
- теги без #, 8-15 штук, без дублювань, релевантні конкретному відео;
- не змінюй thumbnail;
- для Shorts не вигадуй глави;
- chapters дозволені тільки за наявності підтверджених таймкодів у транскрипті;
- поверни ТІЛЬКИ JSON з полями:
  title, title_variants, description, tags, chapters.
- chapters = "" якщо точні таймкоди неможливо підтвердити транскриптом.

SHORTS: {is_short}
ПОТОЧНА НАЗВА:
{current_title}

ПОТОЧНИЙ ОПИС:
{current_description[:6000]}

ПОТОЧНІ ТЕГИ:
{json.dumps(current_tags or [], ensure_ascii=False)}

ПУБЛІЧНИЙ КОНТЕКСТ yt-dlp:
{json.dumps(context, ensure_ascii=False)[:6000]}

ТРАНСКРИПТ:
{transcript[:12000]}
""".strip()

    payload: dict[str, Any] = {}
    last_error: Exception | None = None
    for attempt in range(3):
        system_text = (
            "Працюй як точний редактор метаданих. "
            "Не вигадуй подій, людей, цитат або причин. "
            "Поверни рівно JSON-об'єкт з ключами title, title_variants, description, tags, chapters."
        )
        if attempt:
            system_text += (
                " Попередня відповідь не пройшла валідацію. "
                "Обов'язково заповни title і description. chapters має бути рядком."
            )
        try:
            attempt_prompt = prompt
            if attempt:
                attempt_prompt = f"""
Поверни ТІЛЬКИ валідний JSON з ключами title, title_variants, description, tags, chapters.
title: російською, до 100 символів, конкретний і підтверджений транскриптом.
title_variants: РІВНО 3 різні варіанти, кожен до 100 символів.
description: українською, 350-900 символів, конкретно за змістом транскрипту, без ENGLISH SUMMARY.
tags: масив 8-15 рядків без #, без дублікатів.
chapters: рядок з підтвердженими таймкодами або порожній рядок.
Не вигадуй фактів. Не роби тверджень про економіку, зарплати, соцгарантії чи інші результати, якщо цього немає в транскрипті.

ПОТОЧНА НАЗВА:
{current_title}

ТРАНСКРИПТ:
{transcript[:8000]}
""".strip()
            raw = ollama_chat(
                [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": attempt_prompt},
                ],
                model=model,
                temperature=0.05 if attempt else 0.15,
                json_mode=True,
            )
            candidate = _normalize_seo_candidate(_extract_json_object(raw))
            if not str(candidate.get("title") or "").strip():
                variants_candidate = candidate.get("title_variants") or []
                if isinstance(variants_candidate, list) and variants_candidate:
                    candidate["title"] = str(variants_candidate[0]).strip()
            if not str(candidate.get("title") or "").strip():
                raise ValueError("missing title")
            if not str(candidate.get("description") or "").strip():
                recovered_description = _recover_missing_description(
                    current_title=current_title,
                    transcript=transcript,
                    public_context=context,
                    model=model,
                )
                if recovered_description:
                    candidate["description"] = recovered_description
            if not str(candidate.get("description") or "").strip():
                raise ValueError("missing description")
            variants_candidate = [
                str(item).strip()
                for item in (candidate.get("title_variants") or [])
                if str(item).strip()
            ]
            if (
                len(variants_candidate) < 3
                or len({item.casefold() for item in variants_candidate[:3]}) < 3
            ):
                variants_candidate = _recover_title_variants(
                    current_title=current_title,
                    transcript=transcript,
                    model=model,
                )
                candidate["title_variants"] = variants_candidate
            if len(variants_candidate) < 3:
                raise ValueError("need exactly 3 title variants")
            if len({item.casefold() for item in variants_candidate[:3]}) < 3:
                raise ValueError("title variants must be distinct")
            description_candidate = str(candidate.get("description") or "").strip()
            if transcript.strip() and len(description_candidate) < 320:
                recovered_description = _recover_missing_description(
                    current_title=current_title,
                    transcript=transcript,
                    public_context=context,
                    model=model,
                )
                if recovered_description:
                    candidate["description"] = recovered_description
                    description_candidate = recovered_description
            if transcript.strip() and len(description_candidate) < 320:
                raise ValueError("description too thin for transcript-backed SEO")
            payload = candidate
            break
        except (ValueError, RuntimeError, TimeoutError) as exc:
            last_error = exc
    if not payload:
        raise ValueError(f"Локальна SEO-генерація не пройшла валідацію після повтору: {last_error}")

    title = str(payload.get("title") or "").strip()
    variants = [
        str(item).strip()
        for item in (payload.get("title_variants") or [])
        if str(item).strip()
    ]
    description = str(payload.get("description") or "").strip()
    tags = [
        str(item).strip().lstrip("#")
        for item in (payload.get("tags") or [])
        if str(item).strip()
    ]
    chapters_value = payload.get("chapters")
    if isinstance(chapters_value, str):
        chapters = chapters_value.strip()
    elif isinstance(chapters_value, list):
        lines: list[str] = []
        for item in chapters_value:
            if not isinstance(item, dict):
                continue
            stamp = str(item.get("time") or item.get("timestamp") or item.get("start") or "").strip()
            label = str(item.get("title") or item.get("name") or "").strip()
            if stamp and label and re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", stamp):
                lines.append(f"{stamp} {label}")
        chapters = "\n".join(lines)
    else:
        chapters = ""

    if not title:
        raise ValueError("Локальна модель не створила назву.")
    if len(title) > 100:
        raise ValueError("Локальна модель створила назву довшу за 100 символів.")
    if not description:
        raise ValueError("Локальна модель не створила опис.")
    if len(description) > 5000:
        raise ValueError("Локальна модель створила опис довший за 5000 символів.")
    if is_short:
        chapters = ""

    return {
        "title": title,
        "title_variants": variants[:3],
        "description": description,
        "tags": tags[:15],
        "chapters": chapters,
        "provider": f"ollama:{model}",
        "youtube_data_api_quota": 0,
    }


def generate_comment_reply_local(
    *,
    comment_text: str,
    video_title: str = "",
    video_context: str = "",
    model: str = DEFAULT_OLLAMA_MODEL,
) -> str:
    prompt = f"""
Підготуй ОДНУ коротку чернетку відповіді на опублікований YouTube-коментар
від імені каналу «РАША ГУДБАЙ».

Вимоги:
- українською мовою, якщо коментар не просить інше;
- 1-3 речення;
- спокійно, без образ і погроз;
- не вигадуй фактів;
- не пиши, що відповідь автоматична або створена ШІ;
- якщо коментар політичний/спірний, не вигадуй доказів і не приписуй людині мотиви;
- поверни тільки готовий текст відповіді, без лапок і пояснень;
- це ЛИШЕ ЧЕРНЕТКА: її не буде автоматично опубліковано.

Відео: {video_title}
Контекст відео: {video_context[:4000]}
Коментар:
{comment_text}
""".strip()
    return ollama_chat(
        [
            {
                "role": "system",
                "content": "Створюй лише безпечну чернетку відповіді для ручної перевірки.",
            },
            {"role": "user", "content": prompt},
        ],
        model=model,
        temperature=0.25,
    ).strip()


def parse_google_trends_csv_text(text: str) -> list[dict[str, Any]]:
    """Parse a downloaded Google Trends CSV without network/API calls."""
    cleaned = (text or "").lstrip("\ufeff")
    lines = [line for line in cleaned.splitlines() if line.strip()]
    while lines and (
        lines[0].startswith("Категорія:")
        or lines[0].startswith("Category:")
        or lines[0].startswith("WEB SEARCH")
    ):
        lines.pop(0)
    if not lines:
        return []

    sample = "\n".join(lines[:5])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO("\n".join(lines)), dialect)
    rows = list(reader)
    if len(rows) < 2:
        return []

    header = [str(item).strip() for item in rows[0]]
    result: list[dict[str, Any]] = []
    for row in rows[1:]:
        if not row:
            continue
        padded = row + [""] * max(0, len(header) - len(row))
        item = {header[index]: padded[index].strip() for index in range(len(header))}
        result.append(item)
    return result


def load_google_trends_csv(path: str | Path) -> list[dict[str, Any]]:
    return parse_google_trends_csv_text(
        Path(path).read_text(encoding="utf-8-sig", errors="replace")
    )


def summarize_google_trends(
    rows: list[dict[str, Any]],
    *,
    max_terms: int = 12,
) -> list[dict[str, Any]]:
    """Summarize imported Google Trends rows for local SEO prompting."""
    if not rows:
        return []

    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)

    series: list[dict[str, Any]] = []
    for key in keys:
        values: list[float] = []
        latest: float | None = None
        for row in rows:
            raw = str(row.get(key) or "").strip().replace(",", ".")
            if not raw:
                continue
            raw = re.sub(r"[^0-9.\-]", "", raw)
            try:
                value = float(raw)
            except ValueError:
                continue
            values.append(value)
            latest = value
        if not values:
            continue
        series.append(
            {
                "term": key,
                "latest": latest,
                "average": round(sum(values) / len(values), 2),
                "peak": max(values),
                "samples": len(values),
            }
        )

    series.sort(
        key=lambda item: (
            float(item.get("latest") or 0),
            float(item.get("average") or 0),
            float(item.get("peak") or 0),
        ),
        reverse=True,
    )
    return series[:max_terms]


def load_google_trends_summary(
    path: str | Path,
    *,
    max_terms: int = 12,
) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    clean_rows = [row for row in rows if isinstance(row, dict)]
    return summarize_google_trends(clean_rows, max_terms=max_terms)
