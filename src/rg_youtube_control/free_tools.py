from __future__ import annotations

import csv
import io
import json
import os
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

    if os.getenv("RG_LOCAL_AI_PROVIDER", "lmstudio").strip().lower() == "lmstudio":
        from .lm_studio_client import probe_lm_studio
        local = probe_lm_studio()
        ready = bool(local["available"] and local["model_selected"])
        detail = (
            "LM Studio локально готова"
            if ready else "LM Studio: запустіть сервер і завантажте одну модель"
        )
        probes["lmstudio"] = ToolProbe(
            "LM Studio", bool(local["available"]), detail
        )
        probes["lmstudio_model"] = ToolProbe(
            str(local.get("selected_model") or "LM Studio model"), ready, detail
        )
        # Legacy keys preserved for existing UI callers, but identify
        # LM Studio rather than claim that the removed Ollama is installed.
        probes["ollama"] = ToolProbe("LM Studio (local)", bool(local["available"]), detail)
        probes["ollama_model"] = ToolProbe("LM Studio model", ready, detail)
    else:
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
        "socket_timeout": 15,
        "retries": 1,
        "extractor_retries": 1,
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
        "_caption_tracks": {
            "automatic": info.get("automatic_captions") or {},
            "manual": info.get("subtitles") or {},
        },
        "source": "yt-dlp",
        "youtube_data_api_quota": 0,
    }


def _subtitle_timestamp_seconds(value: str) -> float:
    text = str(value or "").strip().replace(",", ".")
    parts = text.split(":")
    if len(parts) != 3:
        raise ValueError(f"Некоректний SRT-таймкод: {value}")
    hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_srt_transcript(text: str) -> list[dict[str, Any]]:
    """Parse a local SRT transcript into the same row shape as transcript API."""
    blocks = re.split(r"\r?\n\s*\r?\n", str(text or "").strip())
    rows: list[dict[str, Any]] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if lines and lines[0].isdigit():
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        left, right = [part.strip() for part in lines[0].split("-->", 1)]
        try:
            start = _subtitle_timestamp_seconds(left)
            end = _subtitle_timestamp_seconds(right.split()[0])
        except Exception:
            continue
        caption = " ".join(lines[1:]).strip()
        caption = re.sub(r"<[^>]+>", "", caption)
        if not caption:
            continue
        rows.append(
            {
                "text": caption,
                "start": start,
                "duration": max(0.0, end - start),
            }
        )
    return rows


def load_srt_transcript(path: str | Path) -> list[dict[str, Any]]:
    return parse_srt_transcript(
        Path(path).read_text(encoding="utf-8-sig", errors="replace")
    )


def parse_webvtt_transcript(text: str) -> list[dict[str, Any]]:
    """Parse a WebVTT caption track returned by YouTube."""
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    rows: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if "-->" not in line:
            index += 1
            continue
        left, right = [part.strip() for part in line.split("-->", 1)]
        right = right.split()[0]
        try:
            start = _subtitle_timestamp_seconds(left)
            end = _subtitle_timestamp_seconds(right)
        except Exception:
            index += 1
            continue
        index += 1
        text_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index].strip())
            index += 1
        caption = " ".join(text_lines)
        caption = re.sub(r"<[^>]+>", "", caption)
        caption = " ".join(caption.split())
        if caption:
            rows.append(
                {
                    "text": caption,
                    "start": start,
                    "duration": max(0.0, end - start),
                }
            )
        index += 1
    return rows


def fetch_transcript_from_public_metadata(
    context: dict[str, Any],
    languages: Iterable[str] = ("uk", "ru", "en"),
    *,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    """Use caption URLs already discovered by yt-dlp; no YouTube Data API quota."""
    tracks = dict(context.get("_caption_tracks") or {})
    sources = [
        dict(tracks.get("manual") or {}),
        dict(tracks.get("automatic") or {}),
    ]

    language_order = [str(item).casefold() for item in languages]
    for source in sources:
        keys = list(source.keys())
        ordered: list[str] = []
        for wanted in language_order:
            ordered.extend(
                key for key in keys
                if key.casefold() == wanted and key not in ordered
            )
            ordered.extend(
                key for key in keys
                if key.casefold().startswith(wanted + "-") and key not in ordered
            )
        # If YouTube exposes captions only under an unexpected locale, use
        # them rather than treating the video as transcript-less.
        ordered.extend(key for key in keys if key not in ordered)

        for language in ordered:
            formats = list(source.get(language) or [])
            formats.sort(
                key=lambda item: (
                    0 if str(item.get("ext") or "").casefold() == "json3" else
                    1 if str(item.get("ext") or "").casefold() in {"vtt", "webvtt"} else
                    2
                )
            )
            for item in formats:
                url = str(item.get("url") or "").strip()
                ext = str(item.get("ext") or "").casefold()
                if not url or ext not in {"json3", "vtt", "webvtt"}:
                    continue
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 Chrome/154 Safari/537.36"
                        )
                    },
                )
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as response:
                        body = response.read().decode("utf-8", errors="replace")
                except Exception:
                    continue

                if ext in {"vtt", "webvtt"}:
                    rows = parse_webvtt_transcript(body)
                    if rows:
                        return rows
                    continue

                try:
                    payload = json.loads(body)
                except Exception:
                    continue
                rows: list[dict[str, Any]] = []
                for event in payload.get("events") or []:
                    segments = event.get("segs") or []
                    text_value = "".join(
                        str(segment.get("utf8") or "")
                        for segment in segments
                    )
                    text_value = " ".join(text_value.replace("\n", " ").split())
                    if not text_value:
                        continue
                    rows.append(
                        {
                            "text": text_value,
                            "start": float(event.get("tStartMs") or 0) / 1000.0,
                            "duration": float(event.get("dDurationMs") or 0) / 1000.0,
                        }
                    )
                if rows:
                    return rows

    return []


def fetch_transcript(
    video: str,
    languages: Iterable[str] = ("uk", "ru", "en"),
) -> list[dict[str, Any]]:
    """Fetch any usable YouTube transcript without YouTube Data API quota.

    Prefer the requested languages, but do not reject a video merely because
    YouTube labels its only caption track with another locale. When possible,
    translate that track to Russian for a stable fact-grounding input.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
    except Exception as exc:
        raise RuntimeError("youtube-transcript-api не встановлено.") from exc

    video_id = _video_id(video)
    preferred = [str(item) for item in languages]
    api = YouTubeTranscriptApi()

    transcript_obj = None
    transcript_list = api.list(video_id)
    try:
        transcript_obj = transcript_list.find_transcript(preferred)
    except Exception:
        candidates = list(transcript_list)
        if candidates:
            def rank(item: Any) -> tuple[int, int, str]:
                code = str(getattr(item, "language_code", "") or "").casefold()
                prefix_rank = min(
                    (
                        index
                        for index, wanted in enumerate(preferred)
                        if code == wanted.casefold()
                        or code.startswith(wanted.casefold() + "-")
                    ),
                    default=len(preferred),
                )
                generated = 1 if bool(getattr(item, "is_generated", False)) else 0
                return (prefix_rank, generated, code)

            transcript_obj = sorted(candidates, key=rank)[0]

    if transcript_obj is None:
        return []

    code = str(getattr(transcript_obj, "language_code", "") or "").casefold()
    preferred_codes = {item.casefold() for item in preferred}
    preferred_match = any(
        code == wanted or code.startswith(wanted + "-")
        for wanted in preferred_codes
    )
    if not preferred_match and bool(
        getattr(transcript_obj, "is_translatable", False)
    ):
        for target in ("ru", "uk", "en"):
            try:
                transcript_obj = transcript_obj.translate(target)
                break
            except Exception:
                continue

    fetched = transcript_obj.fetch()
    rows = fetched.to_raw_data()
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
    num_ctx: int | None = None,
) -> str:
    # Backward-compatible function name for older callers. The DEFAULT
    # production provider is LM Studio, not Ollama; the latter is available
    # only by explicit legacy opt-in for tests/migrations.
    provider = os.getenv("RG_LOCAL_AI_PROVIDER", "lmstudio").strip().lower()
    if provider == "lmstudio":
        from .lm_studio_client import lm_studio_chat
        selected_model = "" if model == DEFAULT_OLLAMA_MODEL else model
        return lm_studio_chat(
            messages,
            model=selected_model,
            timeout=timeout,
            temperature=temperature,
            json_mode=json_mode,
        )
    if provider != "ollama":
        raise RuntimeError("Unknown local AI provider; use lmstudio")
    request_payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": temperature},
    }
    if num_ctx is not None:
        request_payload["options"]["num_ctx"] = int(num_ctx)
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
    except urllib.error.HTTPError as exc:
        # Ollama /api/tags may work even while model inference returns HTTP
        # 500. Preserve the status without logging response bodies or SRT.
        raise RuntimeError(
            f"Локальна Ollama не виконала запит до моделі (HTTP {exc.code}). "
            "Перевірте стан моделі, GPU та доступну пам'ять."
        ) from exc
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
        "title": (
            "title", "new_title", "video_title", "назва",
            "название", "заголовок", "основное_название", "name",
        ),
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
    variants = normalized.get("title_variants")
    if isinstance(variants, str):
        # A single string is not a list of character-sized A/B titles.
        # Strip only list prefixes; preserve dates/numbers inside SEO titles.
        normalized["title_variants"] = [
            re.sub(r"^\s*(?:[ABCАБВ1-3][.):-]\s*)", "", part).strip()
            for part in variants.splitlines()
            if part.strip()
        ]
    elif not isinstance(variants, list):
        normalized["title_variants"] = []
    return normalized




_GROUNDED_TOPIC_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("лукашенко",), "Лукашенко"),
    (("беларус", "білорус"), "Білорусь"),
    (("шойгу",), "Шойгу"),
    (("министерство обороны", "міністерство оборони"), "Міністерство оборони"),
    (("коррупц", "корупц"), "корупція"),
    (("цены", "цена ", "ціни", "ціна ", "подорожч", "дорожч", "инфляц", "інфляц"), "ціни та вартість життя"),
    (("зарплат", "заработн", "заробітн"), "зарплати"),
    (("доходы", "доходів", "доходи", "доходах", "доходов"), "доходи"),
    (("пенси", "пенсії", "пенсі"), "пенсії"),
    (("соцпакет", "соціальн", "социальн"), "соціальні виплати"),
    (("эконом", "економ"), "економіка"),
    (("путин", "путін"), "Путін у розмові"),
    (("войн", "війн"), "війна"),
    (("украин", "україн"), "Україна"),
    (("мобилиз", "мобіліз"), "мобілізація"),
    (("санкц",), "санкції"),
    (("бензин", "топлив", "пальне"), "паливо"),
    (("азс",), "АЗС"),
    (("работа", "работы", "работу", "робота", "роботи", "роботу", "безработ", "безробіт"), "робота та зайнятість"),
    (("квартир", "жиль", "ипотек", "іпотек"), "житло"),
    (("медицин", "лікар", "боляч", "здоров"), "здоров'я та медицина"),
)




# Conservative title/SRT subject check: important named subjects in the
# existing public title must be mentioned somewhere in the source captions.
# This is a *review warning*, NOT a proof of mismatched files or false speech.
_TITLE_SOURCE_SUBJECT_ROOTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("чечен", ("чечен",)),
    ("дагестан", ("дагестан",)),
    ("шойгу", ("шойгу",)),
    ("бєлоусов", ("белоусов", "бєлоусов")),
    ("саратов", ("саратов",)),
    ("краснодар", ("краснодар",)),
    ("лукашенк", ("лукашенк",)),
    ("путін", ("путин", "путін")),
    ("трамп", ("трамп",)),
    ("польщ", ("польск", "польщ")),
    ("бандер", ("бандер",)),
    ("новосибірськ", ("новосибирск", "новосибірськ")),
    ("петербург", ("петербург",)),
    ("хамас", ("хамас",)),
    ("израил", ("израил", "израиль", "ізраїл", "ізраїль")),
    ("ізраїл", ("израил", "израиль", "ізраїл", "ізраїль")),
    ("осужден", ("осужден", "засуджен", "засудж")),
    ("засуджен", ("осужден", "засуджен", "засудж")),
    ("преступлен", ("преступл", "злочин")),
    ("злочин", ("преступл", "злочин")),
    ("школ", ("школ",)),
    ("центробанк", ("центробанк", "центральн банк")),
    ("подмосков", ("подмосков", "підмосков")),
    ("підмосков", ("подмосков", "підмосков")),
    ("27 лет", ("27 лет", "27 років")),
    ("27 років", ("27 лет", "27 років")),
)


def _seo_title_source_conflicts(title: str, transcript: str) -> list[str]:
    """Warn when a named title subject cannot be found in the supplied SRT."""
    if not str(title or "").strip() or not str(transcript or "").strip():
        return []
    name = str(title).casefold()
    caption = str(transcript).casefold()
    conflicts = []
    for title_root, caption_roots in _TITLE_SOURCE_SUBJECT_ROOTS:
        if title_root in name and not any(root in caption for root in caption_roots):
            conflicts.append("TITLE_SUBJECT_NOT_IN_SRT:" + title_root.upper())
    return conflicts


def _seo_editorial_preview_flags(
    title: str,
    description: str,
    variants: Iterable[str] = (),
    tags: Iterable[str] = (),
) -> list[str]:
    """Reject low-information SEO even when formatting itself passes.

    These are conservative editorial warnings, NOT automatic fact checks.
    """
    from difflib import SequenceMatcher

    primary = " ".join(str(title or "").casefold().split())
    desc = " ".join(str(description or "").casefold().split())
    alternatives = [" ".join(str(x).casefold().split()) for x in variants]
    tag_keys = [" ".join(str(x).casefold().split()) for x in tags]
    flags: list[str] = []
    generic_primary = (
        "про що говорять у чат-рулетці?",
        "що кажуть співрозмовники?",
        "думки учасників розмови",
        "які запитання виникають?",
    )
    generic_headline = re.compile(
        r"^(?:що|про що)\s+(?:думають|говорять|кажуть|"
        r"відповідають|обговорюють)\s+"
        r"(?:росіяни|співрозмовники|учасники)"
        r"(?:\s+(?:сьогодні|в чат.рулетці|про це))?[?!.]?$|"
        r"^(?:думки|розмова|суперечка|дискусія|"
        r"питання|відповідь|реакція)\s+"
        r"(?:росіян|учасників|співрозмовників|у чат.рулетці)[?!.]?$",
        flags=re.I,
    )
    if (
        any(primary.endswith(value) for value in generic_primary)
        or bool(generic_headline.fullmatch(primary))
    ):
        flags.append("GENERIC_PRIMARY_TITLE")
    vague_ab_question = re.compile(
        r"(?:про що (?:йдеться|говорили|говорять|кажуть)|"
        r"що (?:говорять|кажуть) (?:співрозмовники|учасники)|"
        r"думки учасників розмови|які запитання виникають|"
        r"що прозвучало під час розмови|"
        r"що обговорили учасники|"
        r"які оцінки пролунали)"
    )
    if sum(
        any(value in item for value in generic_primary)
        or bool(vague_ab_question.search(item))
        for item in alternatives
    ) >= 1:
        flags.append("GENERIC_AB_VARIANTS")
    if (
        "співрозмовники висловлюють різні версії, особисті оцінки" in desc
        or "дивіться повну розмову та оцініть аргументи" in desc
        or "розмова показує кілька різних поглядів без" in desc
    ):
        flags.append("TEMPLATE_DESCRIPTION")
    if any(value in desc for value in (
        "обговорюють війна проти україни",
        "обговорюють економіка росії",
        "обговорюють робота та зайнятість",
    )):
        flags.append("UNGRAMMATICAL_DESCRIPTION")
    # Format PASS must not hide copy-paste or excessively similar metadata.
    if len(tag_keys) != len(set(tag_keys)):
        flags.append("DUPLICATED_TAGS")
    if sum(len(item.split()) == 1 for item in tag_keys) >= 5:
        flags.append("GENERIC_ONE_WORD_TAGS")
    sentences = [
        item.strip() for item in re.split(r"(?<=[.!?…])\s+", desc)
        if item.strip()
    ]
    if any(
        (a == b or (
            len(a) >= 32 and len(b) >= 32
            and SequenceMatcher(None, a, b).ratio() >= .87
        ))
        for index, a in enumerate(sentences)
        for b in sentences[index + 1:]
    ):
        flags.append("REPEATED_DESCRIPTION_SENTENCES")
    if any(
        SequenceMatcher(None, a, b).ratio() >= .78
        for index, a in enumerate(alternatives)
        for b in alternatives[index + 1:]
    ):
        flags.append("SIMILAR_AB_ANGLES")
    # A few recurring mixed-language errors from actual Qwen captions QA.
    russian_calques = re.compile(
        r"(?<!\w)(?:коллективна|уволили|коррупцию|подмосковье|"
        r"война|киевці|михаил|сдано|виноваты)(?!\w)", flags=re.I
    )
    if any(russian_calques.search(value) for value in (
        title, description, *variants, *tags
    )):
        flags.append("MIXED_LANGUAGE_WORDS")
    if any(re.search(r"(?<!\w)диалог(?!\w)", value, flags=re.I) for value in (
        title, description, *variants, *tags
    )):
        flags.append("RUSSIAN_WORD_DIALOG")
    # Annexation/occupation must not be presented as a verified neutral
    # event merely because a participant said it. Flag for human review.
    sensitive = re.compile(
        r"після\s+входу.{0,40}(?:до\s+рф|до\s+складу\s+росі)"
        r"|(?:входження|приєднання).{0,30}до\s+(?:рф|росі)",
        flags=re.I,
    )
    if any(sensitive.search(str(value)) for value in (
        title, description, *variants
    )):
        flags.append("OCCUPATION_FRAMING_REVIEW")
    return flags

def _grounded_description_from_transcript(
    title: str,
    transcript: str,
) -> str:
    """Build a conservative Ukrainian YouTube description from grounded topics."""
    clean_title = re.sub(
        r"\s*[|·-]\s*(?:РАША\s+ГУДБАЙ|RUSSIA\s+GOODBYE)\s*$",
        "",
        str(title or "").strip(),
        flags=re.I,
    ).strip()

    text = str(transcript or "").casefold()
    title_text = clean_title.casefold()

    topics: list[str] = []
    for needles, label in _GROUNDED_TOPIC_RULES:
        if any(needle in text for needle in needles):
            topics.append(label)
        if len(topics) >= 4:
            break

    if topics:
        topic_text = ", ".join(topics)
        return _polish_generated_description(
            "У цьому випуску чат-рулетки росіяни обговорюють "
            + topic_text
            + ". Співрозмовники висловлюють різні версії, особисті оцінки "
            "та пояснюють, як вони самі бачать причини й наслідки подій. "
            "Позиції помітно відрізняються, тому розмова показує кілька "
            "поглядів на одну тему без нав'язаного висновку. "
            "Дивіться повну розмову та оцініть аргументи співрозмовників самі."
        )

    return _polish_generated_description(
        "У цьому випуску чат-рулетки росіяни відповідають на запитання ведучого "
        "та пояснюють власну позицію щодо теми розмови. Співрозмовники "
        "наводять особисті аргументи, по-різному оцінюють події та сперечаються "
        "про їхні причини. Розмова показує кілька різних поглядів без "
        "нав'язаного висновку. Дивіться повну розмову та оцініть аргументи "
        "співрозмовників самі."
    )


def _deterministic_evidence_description(
    title: str, evidence_report: dict[str, Any],
    *, review_unmapped: list[str] | None = None,
) -> str:
    """Create public Ukrainian prose only from cited, verified discussion subjects.

    Do not publish model-written assertions or raw multilingual ASR topic labels.
    Each verified topic must map to a supported editorial subject.
    """
    blocks = [
        block for block in (evidence_report.get("blocks") or [])
        if isinstance(block, dict) and block.get("verified") is not False
    ]
    if not blocks:
        raise ValueError("No verified transcript quotations for SEO description")

    labels: list[str] = []
    unmapped: list[str] = []
    for block in blocks:
        topics = [item for item in (block.get("topics") or [])
                  if isinstance(item, dict)]
        if not topics:
            raise ValueError("Verified block has no topics")
        for topic in topics:
            quote = str(topic.get("evidence") or "").strip()
            if not quote:
                raise ValueError("No verified transcript quotations for SEO description")
            # Model-written topic labels are proposals, not evidence.
            # Only the literal source quote can establish a public subject.
            combined = quote.casefold()
            recognized: list[str] = []
            # Avoid turning a generic mention of war into an unsupported
            # strategic claim, or any "reason" into a personnel decision.
            if any(w in combined for w in ("войн", "війн")):
                recognized.append("війна")
            if any(w in combined for w in (
                "увольнен", "звільнен", "зміни посади", "смены должност",
                "кадров", "назначен", "призначен",
            )):
                recognized.append("кадрові зміни")
            if (
                any(w in combined for w in ("відповідаль", "ответствен"))
                and any(w in combined for w in ("посадов", "чиновник", "чиновник"))
            ):
                recognized.append("відповідальність посадовців")
            for needles, label in _GROUNDED_TOPIC_RULES:
                if any(needle in combined for needle in needles):
                    recognized.append(label)
            if not recognized:
                # Conversation mechanics are not meaningful SEO subjects.
                if any(phrase in combined for phrase in (
                    "відповідь на запитання", "ответ на вопрос",
                    "реакція на запитання", "ответ собеседника на вопрос",
                )):
                    continue
                unmapped.append(str(topic.get("topic") or "")[:100])
                continue
            for label in recognized:
                if label not in labels:
                    labels.append(label)
    # Unknown ASR topics are NOT public claims. Keep the valid supported
    # subjects, but carry omissions into the manual-review state instead of
    # failing the whole package and repeatedly calling Ollama.
    if unmapped and review_unmapped is not None:
        review_unmapped.extend(unmapped)
    if not labels:
        # No safe public topic exists. Return a precise failure instead of
        # suggesting the unsupported model labels are recognized subjects.
        raise ValueError("No editorial subjects among verified transcript topics")
    if unmapped and review_unmapped is None:
        raise ValueError(
            "Verified subjects require editorial review: " + "; ".join(unmapped[:10])
        )
    labels = labels[:10]
    # Topic labels are verified against transcript quotations above.
    # Keep the public description focused on those subjects rather than
    # padding it with stock claims about what every interviewee supposedly did.
    first = labels[0]
    rest = labels[1:]
    # First in chronology does not mean dominant across the full video.
    lead = "У випуску «РАША ГУДБАЙ» порушено тему: " + first + ". "
    if rest:
        lead += "Також порушуються питання: " + "; ".join(rest) + ". "
    body = (
        "Ці теми згадуються у розмові з росіянами в чат-рулетці. "
        "Окремі твердження учасників є їхніми оцінками, "
        "а не незалежно перевіреними фактами. "
        "Перегляньте обговорення та зіставте позиції співрозмовників."
    )
    result = lead + body
    if len(result) > 950:
        raise ValueError("Evidence subjects exceed editorial description budget")
    return result


def _strip_unverified_putin_motive(description: str) -> str:
    """Remove unsupported assertions of Putin's private rationale for Shoigu decisions."""
    sentences = re.split(r"(?<=[.!?])\s+", str(description or "").strip())
    result = []
    for sentence in sentences:
        lower = sentence.casefold()
        if (
            "путін" in lower or "путин" in lower
        ) and (
            any(x in lower for x in ("утримував", "держав", "тримав", "залишав", "перевів", "уволив", "звільнив"))
        ) and (
            any(x in lower for x in ("щоб", "аби", "для того", "через", "контролюва", "мотив", "причин"))
        ):
            continue
        result.append(sentence)
    return " ".join(result).strip()


def _remove_unsupported_named_claims(
    description: str,
    evidence_report: dict[str, Any],
    current_title: str,
) -> str:
    """Avoid presenting unquoted groups of named people as verified events.

    The transcript's validated evidence quotes, not model-written summaries,
    provide the grounding. Keep the evidence map intact for editorial review.
    """
    def stem(text: str) -> str:
        return text.casefold().translate(str.maketrans({
            "і": "и", "ї": "и", "є": "е", "ґ": "г", "ё": "е"
        }))[:5]

    quoted = " ".join(
        str(item.get("evidence") or "")
        for block in evidence_report.get("blocks") or []
        if block.get("verified") is not False
        for item in block.get("topics") or []
        if isinstance(item, dict)
    )
    supported = {
        stem(word) for word in re.findall(
            r"[A-Za-zА-Яа-яЁёІіЇїЄєҐґ]{5,}",
            str(current_title or "") + " " + quoted
        )
    }
    result: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", description):
        proper = [
            match.group(0)
            for match in re.finditer(r"\b[А-ЯЁІЇЄҐ][а-яёіїєґ]{4,}\b", sentence)
            if match.start() > 2
            and stem(match.group(0)) not in supported
            and stem(match.group(0)) not in {
                "минис", "росии", "росия", "украи", "украй"
            }
        ]
        # A sentence naming two+ otherwise unseen people is an unsupported
        # assertion, not a description of verified dialogue topics.
        if proper:
            continue
        result.append(sentence)
    return " ".join(result).strip()


def _polish_generated_description(value: str) -> str:
    """Remove repeated sentences and obvious LLM-style repetition."""
    text = " ".join(str(value or "").split()).strip()
    text = text.replace("—", "-").replace("–", "-")
    if not text:
        return ""

    replacements = (
        (r"\bуволений\b", "звільнений"),
        (r"\bуволена\b", "звільнена"),
        (r"\bуволено\b", "звільнено"),
        (r"\bувольнення\b", "звільнення"),
        (r"\bувільнення\b", "звільнення"),
        (r"\bзамістників\b", "заступників"),
        (r"\bдолжност[ьи]\b", "посаді"),
        (r"\bдолжность\b", "посада"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)

    sentences = [
        item.strip()
        for item in re.split(r"(?<=[.!?…])\s+", text)
        if item.strip()
    ]
    result: list[str] = []
    seen: set[str] = set()
    opener_counts: dict[str, int] = {}

    for sentence in sentences:
        normalized = re.sub(
            r"[^a-zа-яіїєґё0-9]+",
            " ",
            sentence.casefold(),
        ).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)

        opener = " ".join(normalized.split()[:2])
        if opener:
            opener_counts[opener] = opener_counts.get(opener, 0) + 1
            if opener_counts[opener] > 2:
                continue

        # Drop low-information filler that often appears in local-model output.
        filler = (
            "відбувається згадка",
            "відбувається обговорення",
            "у спілкуванні говорять",
            "у спілкуванні також",
        )
        if any(normalized.startswith(item) for item in filler) and len(result) >= 4:
            continue

        result.append(sentence)

    return " ".join(result).strip()


def _description_quality_error(
    description: str, transcript: str = "", *, max_chars: int = 1000
) -> str:
    """Return a machine-readable reason when a generated SEO description is unsafe."""
    value = " ".join(str(description or "").split()).strip()
    if len(value) < 260:
        return "too_short"
    if len(value) > max_chars:
        return "too_long"

    meta_phrases = (
        "опис побудовано",
        "у тексті збережено",
        "фактичними темами транскрипту",
        "без додавання непідтверджених висновків",
        "у транскрипції",
        "у транскрипті",
        "за транскриптом",
        "транскрипція",
    )
    if any(phrase in value.casefold() for phrase in meta_phrases):
        return "meta_description"

    # A real description should be prose, not a pasted transcript stream.
    sentences = [
        item.strip()
        for item in re.split(r"(?<=[.!?…])\s+", value)
        if item.strip()
    ]
    sentence_marks = len(sentences)
    if sentence_marks < 3:
        return "not_summary_prose"

    normalized_sentences = [
        re.sub(r"[^a-zа-яіїєґё0-9]+", " ", item.casefold()).strip()
        for item in sentences
    ]
    if len(set(normalized_sentences)) < len(normalized_sentences):
        return "duplicate_sentence"

    repetitive_starts = (
        "відбувається ",
        "у спілкуванні ",
        "обговорюють ",
        "припускають ",
    )
    for prefix in repetitive_starts:
        if sum(1 for item in sentences if item.casefold().startswith(prefix)) > 2:
            return "repetitive_style"

    words = re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґЁё0-9]+", value.casefold())
    if len(words) < 45:
        return "too_few_words"

    # Reject clearly Russian transcript dumps. Descriptions for RG are Ukrainian.
    ru_markers = {
        "что", "это", "как", "вот", "просто", "если", "почему", "конечно",
        "россии", "россиян", "жизнь", "людей", "стало", "цены", "всё", "все",
        "ничего", "улучшилась", "зарплату", "пенсию",
    }
    uk_markers = {
        "що", "це", "як", "але", "якщо", "чому", "росії", "росіяни",
        "життя", "людей", "стало", "ціни", "нічого", "покращилося",
        "зарплата", "пенсія", "розмова", "співрозмовник", "відео",
    }
    word_set = set(words)
    ru_hits = len(word_set & ru_markers)
    uk_hits = len(word_set & uk_markers)
    folded_value = value.casefold()
    ukrainian_letters = len(re.findall(r"[іїєґ]", folded_value))
    russian_only_letters = len(re.findall(r"[ыэъё]", folded_value))
    russian_function_words = len(
        re.findall(
            r"\b(?:что|это|как|вот|если|почему|также|или|был|была|были|"
            r"упоминается|обсуждает|затрагиваются|возможн\w*|причин\w*)\b",
            folded_value,
        )
    )
    ukrainian_function_words = len(
        re.findall(
            r"\b(?:що|це|як|але|якщо|чому|також|або|був|була|були|"
            r"згад\w*|обговор\w*|можлив\w*|причин\w*)\b",
            folded_value,
        )
    )
    if ukrainian_letters < 4:
        return "wrong_language"
    if russian_only_letters >= 2:
        return "wrong_language"
    if ru_hits >= 4 and ru_hits > uk_hits * 2:
        return "wrong_language"
    if (
        russian_function_words >= 4
        and russian_function_words > ukrainian_function_words * 2
    ):
        return "wrong_language"

    # Do not promote garbled ASR tokens into an alleged source/outlet.
    suspicious_source_patterns = (
        r"\b(?:в|на)\s+эфире\s+[A-ZА-ЯІЇЄҐ]{2,8}\b",
        r"\bефірі\s+[A-ZА-ЯІЇЄҐ]{2,8}\b",
    )
    for pattern in suspicious_source_patterns:
        if re.search(pattern, value):
            return "unverified_source_entity"

    # Detect near-verbatim transcript copying by n-gram overlap.
    transcript_words = re.findall(
        r"[A-Za-zА-Яа-яІіЇїЄєҐґЁё0-9]+",
        str(transcript or "").casefold(),
    )
    if len(transcript_words) >= 30 and len(words) >= 30:
        n = 6
        source = {
            tuple(transcript_words[i:i+n])
            for i in range(0, max(0, len(transcript_words) - n + 1))
        }
        grams = [
            tuple(words[i:i+n])
            for i in range(0, max(0, len(words) - n + 1))
        ]
        if grams:
            overlap = sum(1 for gram in grams if gram in source) / len(grams)
            if overlap >= 0.35:
                return "transcript_copy"

    return ""


def _repair_description_to_ukrainian(
    *,
    draft: str,
    current_title: str,
    transcript: str,
    model: str,
) -> str:
    """Repair a concrete draft into grounded Ukrainian prose."""
    if not str(draft or "").strip() or not str(transcript or "").strip():
        return ""

    prompt = f"""
Перепиши чернетку SEO-опису українською мовою, звіряючи КОЖНЕ твердження з транскриптом.

Правила:
- 4-6 речень, приблизно 420-750 символів;
- перше речення сформулюй природною українською, НЕ копіюй російську назву відео;
- збережи конкретні теми й позиції, які підтверджені транскриптом;
- видали будь-яку людину, ім'я, посаду, ЗМІ, ефір, організацію або факт, яких немає в транскрипті чи назві;
- не перетворюй припущення співрозмовників на встановлений факт і не додавай причинно-наслідкових висновків від себе;
- якщо твердження про мотиви Путіна, Шойгу, кадрові рішення чи причини звучить лише як думка співрозмовника, обов'язково пиши «деякі співрозмовники вважають/припускають», а не стверджуй це від автора;
- не розширюй імена із зовнішніх знань: якщо є лише «Шойгу», залиш «Шойгу»;
- написання ключових імен та власних назв бери з НАЗВИ відео, якщо вони там є; не перетворюй «Шойгу» на «Шагу», «Шайгу» чи іншу ASR-помилку;
- не перетворюй шумні/обірвані ASR-фрагменти на назви джерел;
- без CTA, без службових фраз, без посилань, хештегів і таймкодів;
- не повторюй речення;
- мова: ТІЛЬКИ українська;
- поверни лише готовий опис.

НАЗВА:
{current_title}

ЧЕРНЕТКА:
{draft}

ТРАНСКРИПТ:
{transcript[:35000]}
""".strip()

    raw = ollama_chat(
        [
            {
                "role": "system",
                "content": (
                    "Ти фактчекер і редактор українських YouTube-описів. "
                    "Використовуй лише наданий транскрипт."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        model=model,
        temperature=0.03,
        json_mode=False,
    )
    value = str(raw or "").strip()
    fence = chr(96) * 3
    if value.startswith(fence):
        value = value[len(fence):].lstrip()
    if value.endswith(fence):
        value = value[:-len(fence)].rstrip()
    value = re.sub(
        r"^\s*(?:Опис|Описание)\s*:\s*",
        "",
        value,
        flags=re.I,
    ).strip().strip('"').strip()
    return _polish_generated_description(value)


def _recover_missing_description(
    *,
    current_title: str,
    transcript: str,
    public_context: dict[str, Any],
    model: str,
) -> str:
    """Focused zero-quota recovery for missing or low-quality descriptions."""
    if not transcript.strip():
        return ""

    last = ""
    last_error = "missing"

    base_prompt = f"""
Створи КОРОТКИЙ SEO-ОПИС українською мовою за змістом транскрипту.
ЦЕ НЕ ТРАНСКРИПТ. НЕ КОПІЮЙ репліки підряд і не вставляй сире розпізнавання мовлення.
Стисни зміст своїми словами у 4-6 грамотних речень, приблизно 420-750 символів.
Перші 1-2 речення конкретно пояснюють, що відбувається у відео.
Якщо в транскрипті є конкретна людина, посада, подія або рішення - назви їх прямо.
Далі передай 2-4 реальні теми, тези або позиції співрозмовників.
Не вигадуй фактів. Не використовуй старий опис як джерело фактів.
НЕ розширюй ім'я або посаду з зовнішніх знань: якщо в джерелі є лише «Шойгу», не пиши «Сергій Шойгу».
Написання ключових імен бери з НАЗВИ відео; не використовуй ASR-помилки «Шагу/Шайгу» замість «Шойгу».
Ігноруй уривки ASR, музику, лайку та нерозбірливі перші секунди. Не вигадуй назву телеканалу, ефіру, програми чи ЗМІ з випадкового токена транскрипту.
Назву джерела/ефіру можна згадати лише якщо вона є в назві відео або чітко повторюється щонайменше двічі в осмисленому контексті.
Не додавай універсальний CTA на кшталт «дивіться повну розмову».
Не додавай посилання, хештеги, ENGLISH SUMMARY, заголовок, службові фрази чи таймкоди.
Не повторюй довгі дослівні фрагменти транскрипту.
Мова опису: ТІЛЬКИ українська.

ПОТОЧНА НАЗВА:
{current_title}

ПУБЛІЧНИЙ КОНТЕКСТ:
{json.dumps(public_context or {}, ensure_ascii=False)[:2200]}

ТРАНСКРИПТ:
{transcript[:12000]}
""".strip()

    for mode in ("json", "text"):
        for attempt in range(2):
            retry_note = ""
            if last_error != "missing":
                retry_note = (
                    f"\n\nПОПЕРЕДНІЙ РЕЗУЛЬТАТ ВІДХИЛЕНО: {last_error}. "
                    "Зроби саме стислий український переказ, а не копію транскрипту."
                )
            if mode == "json":
                prompt = (
                    base_prompt
                    + retry_note
                    + '\n\nПоверни JSON рівно такого формату: {"description":"..."}'
                )
                raw = ollama_chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                "Ти редактор YouTube. Узагальнюй транскрипт своїми словами. "
                                "Поверни тільки JSON з одним ключем description."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    model=model,
                    temperature=0.08,
                    json_mode=True,
                )
                recovered = _normalize_seo_candidate(_extract_json_object(raw))
                value = str(recovered.get("description") or "").strip()
            else:
                prompt = (
                    base_prompt
                    + retry_note
                    + "\n\nПоверни ТІЛЬКИ готовий опис без JSON, лапок і пояснень."
                )
                raw = ollama_chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                "Напиши лише стислий український SEO-опис. "
                                "Не копіюй транскрипт дослівно."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    model=model,
                    temperature=0.10,
                    json_mode=False,
                )
                value = str(raw or "").strip()
                fence = chr(96) * 3
                if value.startswith(fence):
                    value = value[len(fence):].lstrip()
                if value.endswith(fence):
                    value = value[:-len(fence)].rstrip()
                value = re.sub(
                    r"^\s*(?:Опис|Описание)\s*:\s*",
                    "",
                    value,
                    flags=re.I,
                )
                value = value.strip().strip('"').strip()

            value = _polish_generated_description(value)
            if len(value) > len(last):
                last = value
            last_error = _description_quality_error(value, transcript)
            if not last_error:
                return value

            if last_error in {
                "wrong_language",
                "unverified_source_entity",
                "duplicate_sentence",
                "repetitive_style",
            }:
                repaired = _repair_description_to_ukrainian(
                    draft=value,
                    current_title=current_title,
                    transcript=transcript,
                    model=model,
                )
                repaired_error = _description_quality_error(
                    repaired,
                    transcript,
                )
                if repaired and not repaired_error:
                    return repaired
                if len(repaired) > len(last):
                    last = repaired
                if repaired_error:
                    last_error = repaired_error

    return ""


def _ab_distinct_evidence_brief(report: dict[str, Any]) -> str:
    """Up to three distinct grounded anchors; never invent a third story."""
    from .dialogue_seo import distinct_evidence_topics

    entries = distinct_evidence_topics(report)
    if not entries:
        return ""
    n = len(entries)
    selections: list[int] = []
    targets = [0] if n == 1 else ([0, n - 1] if n == 2 else [0, (n - 1) // 2, n - 1])
    for target in targets:
        remaining = [i for i in range(n) if i not in selections]
        selections.append(min(remaining, key=lambda i: abs(i - target)))
    return "\n".join(
        f"{label}: [{entries[i]['start_stamp']}] ТЕМА: {entries[i]['topic']}; "
        f"ЦИТАТА: {entries[i]['evidence'][:220]}"
        for label, i in zip(("A", "B", "C"), selections)
    )


def _source_quote_ab_titles(
    report: dict[str, Any],
    current_title: str = "",
) -> list[str]:
    """Fail-safe REVIEW titles made from verbatim quotes in different blocks.

    This never infers facts from a model-generated topic. Every visible
    quoted phrase is a contiguous excerpt of an actual transcript quote.
    A shortened quote ends in an ellipsis, and no titles are auto-published.
    """
    from itertools import combinations
    from .dialogue_seo import distinct_evidence_topics

    candidates: list[tuple[int, str]] = []
    verified_quotes = {entry["evidence"].casefold() for entry in distinct_evidence_topics(report)}
    for index, block in enumerate(report.get("blocks") or []):
        if not isinstance(block, dict) or block.get("verified") is False:
            continue
        for topic in block.get("topics") or []:
            if not isinstance(topic, dict):
                continue
            quote = " ".join(str(topic.get("evidence") or "").split())
            quote = quote.strip(' "«»„“”')
            if quote.casefold() not in verified_quotes:
                continue
            # Short, complete quotes are valid evidence too; do not silently
            # drop them just because they are under 30 characters. A bare
            # interjection or two-word fragment is too weak for a headline.
            if len(quote) < 15 or len(quote.split()) < 3:
                continue
            excerpt = quote
            if len(excerpt) > 75:
                excerpt = excerpt[:76].rsplit(" ", 1)[0].rstrip(" ,.;:")
                if len(excerpt) < 30:
                    continue
                excerpt += "…"
            title = f"«{excerpt}» | ЧАТ РУЛЕТКА"
            if not 20 <= len(title) <= 100:
                continue
            if title.casefold() == current_title.strip().casefold():
                continue
            candidates.append((index, title))
            break  # only one quoted story per timeline block
    if len(candidates) < 3:
        return []
    # A long stream can contain hundreds of valid quotations. Searching all
    # combinations is cubic and previously stalled multi-hour transcripts.
    # Keep an evenly spaced, chronological subset (including both ends).
    if len(candidates) > 24:
        last = len(candidates) - 1
        candidates = [candidates[round(i * last / 23)] for i in range(24)]
    # Pick the widest temporal coverage first; do not take three adjacent
    # quotes from one conversation when later material exists.
    triplets = sorted(
        combinations(candidates, 3),
        key=lambda triplet: (
            -(triplet[-1][0] - triplet[0][0]),
            abs(triplet[1][0] - (triplet[0][0] + triplet[-1][0]) / 2),
        ),
    )
    for triple in triplets:
        titles = [title for _, title in triple]
        if not ab_title_issues(titles, report):
            return titles
    return []


def _verified_source_ab_titles(
    report: dict[str, Any], current_title: str,
) -> list[str]:
    """Generic REVIEW-ONLY A/B proposals from distinct quoted topics.

    No subject-specific names or handcrafted political events. Only topic
    labels paired with verbatim, verified quotations can be used. This is
    fallback presentation for editors, NOT a fact-checked publishable result.
    """
    # Preserve all candidate labels until the source check is performed.
    # Deduplicating by quotation first can let a bogus model topic shadow
    # the legitimate one that shares its source excerpt.
    from itertools import combinations

    entries = [
        (block_index, item)
        for block_index, block in enumerate(report.get("blocks") or [])
        if isinstance(block, dict) and block.get("verified") is not False
        for item in block.get("topics") or []
        if isinstance(item, dict) and str(item.get("evidence") or "").strip()
    ]
    if not entries:
        return []

    # Labels are authored by the evidence model and thus require review.
    # Reject clearly Russian strings, conversation mechanics and ASR noise.
    generic = (
        "дискусія", "розмова", "відповідь на запитання",
        "реакція на запитання", "обговорення", "питання",
        "різні погляди", "спілкування",
    )
    proposals: list[tuple[int, str]] = []
    subjects: set[str] = set()
    used_quotes: set[str] = set()
    endings = (
        "що говорять співрозмовники?",
        "які оцінки пролунали?",
        "що обговорили учасники?",
    )
    for block_index, entry in entries:
        subject = " ".join(str(entry.get("topic") or "").split())
        source = str(entry.get("evidence") or "")
        if not (5 <= len(subject) <= 66 and len(source) >= 16):
            continue
        low = subject.casefold()
        if any(word in low for word in generic) or re.search(r"[ыэъё]", low):
            continue
        if re.search(r"(?i)\b(?:шагу|шогу|срашк[аи])\b", low):
            continue

        # A label must share a recognizable subject with the quotation;
        # generic function words and model-only named claims are forbidden.
        from .dialogue_seo import _cross_language_topic_word
        label_roots = {
            _cross_language_topic_word(w)[:5]
            for w in re.findall(r"[а-яіїєґa-z]{5,}", low)
            if w not in {"через", "після", "версії", "причини", "причина"}
        }
        quote_roots = {
            _cross_language_topic_word(w)[:5]
            for w in re.findall(r"[а-яіїєґa-z]{5,}", source.casefold())
        }
        # ALL substantive label subjects must be visible in the quote.
        # A single overlapping name may not launder an invented extra claim.
        if not label_roots or not label_roots.issubset(quote_roots):
            continue
        key = re.sub(r"[^а-яіїєґa-z0-9]+", " ", low).strip()
        quote_key = " ".join(source.casefold().split())
        if key in subjects or quote_key in used_quotes:
            continue
        subjects.add(key)
        used_quotes.add(quote_key)
        subject = subject[0].upper() + subject[1:].rstrip(" .?!:;")
        proposed = f"{subject}: {endings[len(proposals) % len(endings)]}"
        if len(proposed) > 100:
            proposed = f"{subject}: що кажуть співрозмовники?"
        if 20 <= len(proposed) <= 100:
            proposals.append((block_index, proposed))
        if len(proposals) >= 24:
            break
    if len(proposals) == 2:
        # Two *separately quoted and root-verified* Ukrainian subjects may
        # support a third neutral overview angle. This never pretends a third
        # event happened and never uses an unverified model topic.
        left = proposals[0][1].split(":", 1)[0]
        right = proposals[1][1].split(":", 1)[0]
        angles = [
            proposals[0][1], proposals[1][1],
            f"{left} та {right}: що обговорили співрозмовники?",
        ]
        if not ab_title_issues(angles, report):
            return angles
    if len(proposals) < 3:
        # With fewer than two supported topics, do not pad or auto-publish.
        return [title for _, title in proposals]

    # A previous bug returned the *first* three topical labels, even when two
    # reused a story. Evaluate other verified subjects instead of fabricating
    # a new one or weakening the editorial gate. Prefer different time blocks.
    def rank(triple: tuple[tuple[int, str], ...]) -> tuple[int, int, int]:
        # Distinct *subject roots* outrank three editorial phrasings of one
        # recurring event. Ignore generic protagonists (e.g. 'Шойгу'), which
        # can legitimately appear in headlines about different events.
        roots = []
        for _, title in triple:
            subject = title.split(":", 1)[0].casefold()
            roots.append({
                _cross_language_topic_word(word)[:5]
                for word in re.findall(r"[а-яіїєґa-z]{5,}", subject)
                if _cross_language_topic_word(word)[:5] not in {
                    "шойгу", "шойг", "росси", "росия", "путин",
                    "украи", "участ", "розмо",
                }
            })
        repeats = sum(
            bool(roots[left] & roots[right])
            for left, right in ((0, 1), (0, 2), (1, 2))
        )
        indices = [index for index, _ in triple]
        return (repeats, -len(set(indices)), -(max(indices) - min(indices)))

    triplets = sorted(combinations(proposals, 3), key=rank)
    for triple in triplets:
        titles = [title for _, title in triple]
        if not ab_title_issues(titles, report):
            return titles
    # No fully supported independent triplet: preserve a review-only preview
    # rather than ever declaring the A/B set safe or inventing events.
    return [title for _, title in proposals[:3]]


def _recover_independent_ab_titles(
    *,
    report: dict[str, Any],
    current_title: str,
    model: str,
) -> list[str]:
    """Generate one verified Ukrainian hook per separate dialogue story."""
    outline = _ab_distinct_evidence_brief(report)
    anchors = outline.splitlines() if outline else []
    if len(anchors) < 2:
        return []
    # Two genuinely different verified subjects can support three A/B
    # angles: the third must reinterpret the FIRST confirmed subject, not
    # pretend that a third story exists. This fixes 2-block real videos.
    two_subjects = len(anchors) == 2
    if two_subjects:
        anchors.append(anchors[0])
    titles: list[str] = []
    for index, source_anchor in enumerate(anchors[:3], 1):
        reuse_note = (
            "Це третій РАКУРС першої підтвердженої теми, НЕ нова подія. "
            "Не додавай фактів, яких немає у цитаті. "
            if two_subjects and index == 3 else ""
        )
        prompt = (
            f"Напиши ОДНУ назву українською, 25-95 символів, "
            f"тільки про підтверджену тему {index}:\n{source_anchor}\n"
            + reuse_note + "\n"
            "Без вигаданих фактів, персонажів чи причин. "
            "Сформулюй конкретний гачок за цитатою. "
            "Не повторюй інші сюжети та назви. "
            'Поверни JSON лише {"title":"..."}.\n'
            f"ПОТОЧНА НАЗВА (НЕ КОПІЮВАТИ): {current_title}\n"
            f"ВЖЕ ВИКОРИСТАНІ НАЗВИ: {json.dumps(titles, ensure_ascii=False)}"
        )
        try:
            raw = ollama_chat(
                [{"role": "system", "content": "Точний редактор. Тільки JSON."},
                 {"role": "user", "content": prompt}],
                model=model, timeout=90.0, temperature=0.12, json_mode=True,
            )
            item = _normalize_seo_candidate(_extract_json_object(raw))
            title = str(item.get("title") or "").strip()
        except (ValueError, RuntimeError, TimeoutError):
            # Do not erase two valid hooks because one model request failed.
            continue
        if not 25 <= len(title) <= 100:
            continue
        if title.casefold() == current_title.strip().casefold():
            continue
        if any(title.casefold() == existing.casefold() for existing in titles):
            # A repeat on the second story is proof that this model pass is
            # not producing independent hooks; skip further model requests.
            return _source_quote_ab_titles(report, current_title)
        titles.append(title)
    if len(titles) == 3:
        # Content-grounding is validated by the outer AB gate. Do not erase
        # the model's three distinct answers solely because one is a paraphrase.
        return titles
    # A direct source quotation is less polished but is never invented and
    # is always displayed for manual review when the model is unreliable.
    return _source_quote_ab_titles(report, current_title)


def _grounded_review_title_variants(
    current_title: str,
    transcript: str,
    *,
    pool_size: int = 3,
) -> list[str]:
    """Review-only question angles for topics actually mentioned in captions.

    Extra pool option exists because the first candidate can become the
    primary title, leaving three separate A/B slots to fill. Never invent an
    additional event to fill those slots.
    """
    source = str(transcript or "").casefold()
    if not source.strip():
        return []
    weak_stems = {"цен", "сво", "президент", "министерств", "оборон"}
    matched: list[tuple[int, int, str]] = []
    for order, (needles, label) in enumerate(_GROUNDED_TOPIC_RULES):
        # One subject containing two synonyms is not mentioned twice.
        count = max(
            (source.count(needle) for needle in needles if needle not in weak_stems),
            default=0,
        )
        if count:
            matched.append((-count, order, label))
    matched.sort()
    labels = [label for _, _, label in matched]
    if not labels:
        return []

    # All four are neutral angles on observed subjects, not extra events.
    # The QA preview may use the first for a missing primary title, leaving
    # three alternatives. For one subject, questions vary without new facts.
    suggestions = [
        f"{labels[0]}: про що говорять у чат-рулетці?",
        f"{labels[1] if len(labels) > 1 else labels[0]}: що кажуть співрозмовники?",
        f"{labels[2] if len(labels) > 2 else labels[0]}: які запитання виникають?",
        f"{labels[3] if len(labels) > 3 else labels[0]}: думки учасників розмови",
    ]
    return [title for title in suggestions[:pool_size] if len(title) <= 100]



def _improve_review_ab_distinctness(
    title: str,
    variants: list[str],
    transcript: str,
    evidence_report: dict[str, Any] | None = None,
) -> tuple[list[str], bool]:
    """Improve repeated A/B hooks using only topics detected in transcript.

    This is a review-only fallback. Editorial approval requires verifying the
    actual transcript and cannot be inferred from three well-formed titles.
    """
    from itertools import combinations

    if len(variants) != 3 or not transcript.strip():
        return variants, False
    initial_issues = ab_title_issues(variants, evidence_report)
    if not initial_issues:
        return variants, False
    grounded = [
        item for item in _grounded_review_title_variants("", transcript, pool_size=4)
        if item.casefold() != title.casefold()
        and not _seo_ukrainian_language_issue(item)
    ]
    if len(grounded) < 3:
        return variants, False
    pool = list(dict.fromkeys([*variants, *grounded]))
    best = variants
    best_score = len(initial_issues)
    for option in combinations(pool, 3):
        # Replacing a single word in an unchecked model headline does not
        # establish grounding; favor multiple transcript-topic candidates.
        if sum(item in grounded for item in option) < 2:
            continue
        issues = ab_title_issues(option, evidence_report)
        if len(issues) < best_score:
            best, best_score = list(option), len(issues)
            if best_score == 0:
                break
    return best, best != variants


def _recover_title_variants(
    *,
    current_title: str,
    transcript: str,
    model: str,
) -> list[str]:
    """Focused recovery of exactly three distinct Ukrainian title variants."""
    prompt = f"""
Створи РІВНО 3 різні варіанти назви YouTube-відео українською.
A: головний конфлікт у розмові; B: конкретне запитання або парадокс;
C: інша підтверджена тема, якщо вона є; інакше інший кут головної теми.
Не починай усі три однаково. Назви мають відрізнятися змістом і кутом.
Кожна до 100 символів. Лише факти та теми, підтверджені транскриптом.
Без вигаданих цитат і без непідтвердженого клікбейту.
Поверни JSON:
{{"title_variants":["...","...","..."]}}

ПОТОЧНА НАЗВА:
{current_title}

ТРАНСКРИПТ:
{transcript[:35000]}
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


_GENERIC_MODEL_TAGS = {
    "план", "стратегия", "политика", "должность", "перевод", "власть",
    "тема", "мнение", "разговор", "видео", "вопрос", "ответ", "общество",
    "новости", "события", "ситуация", "анализ", "обсуждение", "интервью",
}


# Explicit cross-language lexical equivalences for Ukrainian SEO queries and
# Russian-language conversation SRT. Do not infer a relationship between
# tokens unless their roots occur in ONE nearby source-caption span.
_TAG_GROUNDING_ROOTS: dict[str, tuple[str, ...]] = {
    "війн": ("війн", "войн"),
    "росі": ("росі", "росси", "россий", "рф"),
    "росіян": ("росіян", "россиян"),
    "україн": ("україн", "украин"),
    "білорус": ("білорус", "беларус", "белорус"),
    "зарплат": ("зарплат", "заробітн"),
    "пенсі": ("пенсі", "пенси"),
    "звільнен": ("звільнен", "увольнен", "отстав"),
    "звільн": ("звільн", "увольн", "отстав"),
    "мобіліз": ("мобіліз", "мобилиз"),
    "санкці": ("санкці", "санкц"),
    "корупці": ("корупці", "коррупц"),
    "економі": ("економі", "эконом"),
    "бензин": ("бензин", "топлив", "пальн"),
    "пальн": ("пальн", "топлив", "бензин"),
    "путін": ("путін", "путин"),
    "шойгу": ("шойгу",),
    "ціни": ("ціни", "цены", "цен"),
    "вартіст": ("вартіст", "стоимост"),
    "доход": ("доход", "дохід"),
    "робот": ("работа", "работу", "работы", "робота", "роботу", "роботи"),
    "діти": ("діти", "дітей", "дети", "детей", "ребен", "детьми"),
    "загибл": ("загибл", "погиб", "умер", "вбит", "убит"),
    "сім": ("сім", "семь", "семьей", "семьёй", "семьи", "семью"),
    "алкогол": ("алкогол", "пьян", "спиртн"),
    "вибор": ("вибор", "выбор", "голосован", "голосова"),
    "голосуван": ("голосуван", "голосован", "голосова"),
    "голосува": ("голосува", "голосован", "голосова"),
    "переїзд": ("переїзд", "переех", "переезд", "переезж"),
    "виїзд": ("виїзд", "выезд", "уезж"),
    "кордон": ("кордон", "границ", "рубеж"),
    "віра": ("віра", "вера", "веры", "веру", "віру"),
    "страх": ("страх", "боюсь", "боязн", "страшн"),
}

_TAG_CONNECTORS = {"проти", "щодо", "через", "після", "перед", "між",
                   "разом", "військові", "російські"}


def _tag_is_grounded(tag: str, current_title: str, transcript: str) -> bool:
    """Require search queries to occur in one nearby SRT span, across UA/RU.

    Old code required the UKRAINIAN word to appear literally in the RUSSIAN
    subtitle. This silently stripped relevant SEO from almost every dialogue.
    Equivalences below are lexical, not proof of any event's truth.
    """
    clean = " ".join(str(tag or "").split()).strip().lstrip("#")
    if not clean:
        return False
    folded = clean.casefold()
    if folded in _GENERIC_MODEL_TAGS:
        return False
    if re.match(r"^(?:війна|война)\s+(?:і|и)\s+", folded):
        return False
    if folded in {"раша гудбай", "чат рулетка"}:
        return True
    haystack = (transcript if str(transcript or "").strip() else current_title).casefold()
    if not haystack:
        return False
    # The source's actual words establish both entity and topic in one span.
    tag_words = re.findall(r"[a-zа-яіїєґё0-9]+", folded)
    tokens = [
        token for token in tag_words
        if (len(token) >= 4 or token == "сім") and token not in _GENERIC_MODEL_TAGS
        and token not in _TAG_CONNECTORS
    ]
    if not tokens:
        return False

    def match(token: str, words: list[str]) -> bool:
        # Root detection must use word starts, never arbitrary substrings:
        # 'робот' cannot be mistaken for 'робота' unless explicitly scoped
        # and 'свою' must never match 'СВО'.
        root = next(
            (key for key in sorted(_TAG_GROUNDING_ROOTS, key=len, reverse=True)
             if token.startswith(key)),
            None,
        )
        if root:
            variants = _TAG_GROUNDING_ROOTS[root]
            if root == "робот":
                # Exact inflected forms avoid matching a physical "робот"
                # when the SEO phrase refers to human employment.
                return any(word in variants for word in words)
        else:
            length = min(6, max(4, len(token) - 2))
            variants = (token[:length],)
        return any(
            word.startswith(variant)
            for variant in variants
            for word in words
        )

    # Line-level locality prevents mixing disparate speakers' statements.
    # Subtitles with long unbroken lines use overlapping bounded windows.
    for line in haystack.splitlines():
        spans = (
            [line[i:i + 420] for i in range(0, len(line), 300)]
            if len(line) > 420 else [line]
        )
        for span in spans:
            source_words = re.findall(r"[a-zа-яіїєґё0-9]+", span)
            if all(match(token, source_words) for token in tokens):
                return True
    # A topic often spans neighboring subtitle cues. Allow combinations
    # only within a 12-second, at-most-three-cue timestamped window.
    # Never combine distant topics or untimed unrelated sentences.
    previous: list[tuple[float, str]] = []
    for line in haystack.splitlines():
        stamp = re.match(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*", line)
        if not stamp:
            previous.clear()
            continue
        parts = [int(value) for value in stamp.group(1).split(":")]
        seconds = (
            parts[0] * 60 + parts[1] if len(parts) == 2
            else parts[0] * 3600 + parts[1] * 60 + parts[2]
        )
        previous = [(t, v) for t, v in previous if 0 <= seconds - t <= 12]
        previous.append((seconds, line[stamp.end():]))
        recent = previous[-3:]
        if len(recent) >= 2:
            nearby_words = re.findall(
                r"[a-zа-яіїєґё0-9]+", " ".join(v for _, v in recent)
            )
            if all(match(token, nearby_words) for token in tokens):
                return True
    return False



def _source_mentions(
    current_title: str,
    transcript: str,
    roots: tuple[str, ...],
) -> tuple[bool, int]:
    """Count topic mentions by spoken word, never arbitrary substrings.

    When subtitles exist, current_title must not independently establish
    a claimed topic. Count at most one mention per caption line so three
    repeated words in a single fragment do not qualify a topic as recurrent.
    """
    source = str(transcript or "").strip()
    title = str(current_title or "").casefold() if not source else ""
    normalized_roots = tuple(
        str(root).casefold() for root in roots if str(root).strip()
    )
    if not normalized_roots:
        return False, 0

    def matches(line: str) -> bool:
        words = re.findall(r"[a-zа-яіїєґё0-9]+", line.casefold())
        return any(
            word.startswith(root)
            for word in words for root in normalized_roots
        )

    in_title = bool(title and matches(title))
    mentions = sum(1 for line in source.splitlines() if matches(line))
    return in_title, mentions


def _grounded_tags_from_transcript(
    current_title: str,
    transcript: str,
) -> list[str]:
    """Build topical tags from captions; title alone is not content evidence."""
    title = re.sub(
        r"\s*[|·-]\s*(?:РАША\s+ГУДБАЙ|RUSSIA\s+GOODBYE)\s*$",
        "",
        str(current_title or "").strip(),
        flags=re.I,
    ).strip()
    # Do not derive claimed topics from a historical title when captions exist.
    evidence_title = "" if str(transcript or "").strip() else title
    haystack = f"{evidence_title}\n{transcript}".casefold()

    tags: list[str] = ["РАША ГУДБАЙ", "чат рулетка"]

    def add(value: str) -> None:
        clean = " ".join(str(value or "").split()).strip().lstrip("#")
        if not clean:
            return
        if clean.casefold() not in {item.casefold() for item in tags}:
            tags.append(clean)

    # Expand real topic coverage with curated UA equivalents of common RU
    # caption phrases. Every combined query must be proved in ONE subtitle
    # line, never by joining different conversations. A useful sparse SRT
    # is allowed to return fewer than eight tags and fail review honestly.
    episode_queries = (
        "мобілізація в Росії", "росіяни про мобілізацію",
        "ставлення росіян до війни", "росіяни про війну",
        "війна в Україні", "Путін і війна",
        "вибори в Росії", "голосування за Путіна",
        "голосувати за Путіна", "підтримка Путіна",
        "війна та діти", "загиблі діти",
        "сім'я та алкоголь", "мобілізація та сім'я",
        "виїзд за кордон", "страх переїзду",
        "життя в Росії", "робота в Росії",
        "переїзд за кордон", "розмова про віру",
    )
    for phrase in episode_queries:
        if _tag_is_grounded(phrase, evidence_title, transcript):
            add(phrase)
    # A few specific one-word topic queries are legitimate when a broader
    # two-word relationship cannot be supported in one source window.
    # Do not use generic topical filler or invent an unsourced relation.
    for phrase in ("мобілізація", "вибори", "Путін", "санкції", "Шойгу"):
        if _tag_is_grounded(phrase, evidence_title, transcript):
            add(phrase)

    # Named entities and concrete episode topics come before generic channel tags.
    if "шойгу" in haystack:
        add("Шойгу")
        # Only the same caption mentioning Shoigu and dismissal supports
        # the combined search phrase. Include both RU and UA inflections.
        if _tag_is_grounded("звільнення Шойгу", evidence_title, transcript):
            add("звільнення Шойгу")
    if "герасим" in haystack:
        add("Герасимов")
    if "пригож" in haystack:
        add("Пригожин")
    if "белоусов" in haystack:
        add("Белоусов")
    if "тимур" in haystack and "иванов" in haystack:
        add("Тимур Иванов")
    if "лукашенко" in haystack:
        add("Лукашенко")
    if "беларус" in haystack:
        add("Білорусь")
        if "украин" in haystack or "україн" in haystack:
            add("Білорусь і Україна")
    if "украин" in haystack or "україн" in haystack:
        add("Україна")
    if "совет" in haystack and "безопас" in haystack:
        add("Рада безпеки РФ")
    if "министерств" in haystack and "оборон" in haystack:
        add("Міністерство оборони РФ")
    if "коррупц" in haystack:
        add("корупція в Росії")
    if "арм" in haystack and ("росси" in haystack or "рф" in haystack):
        add("російська армія")

    if "росси" in haystack or "росія" in haystack:
        for value in (
            "Росія",
            "росіяни",
            "думки росіян",
            "запитання росіянам",
        ):
            add(value)

    if "жизн" in haystack or "житт" in haystack:
        add("життя в Росії")
    if "цен" in haystack or "дорог" in haystack or "инфляц" in haystack:
        add("ціни в Росії")
    if "зарплат" in haystack or "доход" in haystack:
        add("зарплати в Росії")
    if "пенси" in haystack or "соцпакет" in haystack:
        add("пенсії в Росії")
    in_title, mentions = _source_mentions(evidence_title, transcript, ("эконом", "економ"))
    if in_title or mentions >= 3:
        add("економіка Росії")
    in_title, mentions = _source_mentions(evidence_title, transcript, ("путин", "путін"))
    if in_title or mentions >= 3:
        add("Путін")
    in_title, mentions = _source_mentions(
        evidence_title, transcript, ("войн", "війн", "спецоперац")
    )
    if in_title or mentions >= 3:
        add("війна Росії проти України")
    in_title, mentions = _source_mentions(
        evidence_title, transcript, ("мобилиз", "мобіліз")
    )
    if in_title or mentions >= 3:
        add("мобілізація в Росії")
    in_title, mentions = _source_mentions(evidence_title, transcript, ("санкц",))
    if in_title or mentions >= 3:
        add("санкції проти Росії")
    if "бензин" in haystack or "топлив" in haystack or "азс" in haystack:
        add("бензин у Росії")
    in_title, mentions = _source_mentions(evidence_title, transcript, ("безработ", "работа ", "робота ", "работу ", "роботу "))
    if in_title or mentions >= 4:
        add("робота в Росії")
    if "квартир" in haystack or "жиль" in haystack or "ипотек" in haystack:
        add("житло в Росії")
    if "медицин" in haystack or "здоров" in haystack or "боляч" in haystack:
        add("здоров’я в Росії")
    if re.search(r"\b2023\b", haystack):
        add("Росія 2023")

    # Project-format fallbacks are added last, only to reach a useful minimum.
    for value in (
        "опитування росіян",
        "реакція росіян",
        "розмова з росіянами",
        "чат рулетка з росіянами",
    ):
        if len(tags) >= 8:
            break
        add(value)

    # This deterministic fallback must obey the SAME local SRT grounding
    # gate as model-generated tags. Otherwise words from unrelated dialogues
    # could be combined into fabricated claims ("Білорусь і Україна",
    # "звільнення Шойгу") and bypass the model-tag filter entirely.
    return [
        item for item in tags
        if _tag_is_grounded(item, evidence_title, transcript)
    ][:15]


def _clean_project_title_for_seo(value: str) -> str:
    """Remove legacy channel promo suffixes/handles from an SEO title."""
    text = " ".join(str(value or "").split()).strip()
    text = re.sub(
        r"\s*@RUSSIAGOODBYE(?:_LIVE)?\b",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\s*[|·]\s*РАША\s+ГУДБАЙ(?:\s+СТРИМ)?\s*[👍🔥]*\s*$",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s{2,}", " ", text).strip(" |·-")
    text = re.sub(r"\bБеларусский\b", "Белорусский", text, flags=re.I)
    text = re.sub(r"\bБеларус\b", "Беларусь", text, flags=re.I)
    return text.strip()


def _chapters_are_generic(chapters: str) -> bool:
    labels = [label.casefold() for _stamp, label in _chapter_lines(chapters)]
    if not labels:
        return False
    generic = (
        "вступ",
        "наступний блок",
        "основна частина",
        "фінальна частина",
        "завершення",
        "початок",
        "розвиток головної теми",
        "думки співрозмовників",
        "подальше обговорення",
        "підсумок розмови",
        "розвиток розмови",
        "головна тема",
    )
    return all(any(token in label for token in generic) for label in labels)


_SEO_RUSSIAN_MARKERS = re.compile(
    r"(?<![\\w])(?:увольнение|коррупция|россия|россии|россияне|"
    r"война|путин|мобилизация|санкции|говорят|идет|почему|"
    r"вопросы|ответы|жизнь|мнение|работа|зарплаты|пенсии)(?![\\w])",
    re.I,
)


def _seo_ukrainian_language_issue(value: str) -> bool:
    """Use the same conservative Ukrainian language rule as the QA gate."""
    from .seo_quality_gate import language_error

    return language_error(value)


def _preserve_current_title_when_candidate_is_not_stronger(
    current_title: str,
    candidate_title: str,
) -> str:
    """Keep the current title when the candidate only strips punctuation/branding."""
    current = " ".join(str(current_title or "").split()).strip()
    candidate = " ".join(str(candidate_title or "").split()).strip()
    if not current:
        return candidate
    if not candidate:
        return current

    def core(value: str) -> str:
        value = re.sub(
            r"\s*[|·-]\s*(?:РАША\s+ГУДБАЙ|RUSSIA\s+GOODBYE)\s*$",
            "",
            value,
            flags=re.I,
        )
        value = re.sub(r"[!?.,:;«»\"'()]+", " ", value)
        return " ".join(value.casefold().split())

    current_core = core(current)
    candidate_core = core(candidate)

    # Do not preserve a legacy Russian title over a valid Ukrainian proposal.
    # Project metadata can retain Russian titles from earlier uploads, while
    # current editorial output must use Ukrainian. A weak candidate still goes
    # through the existing evidence/quality review before it can be applied.
    russian_markers = (
        "увольнение", "коррупция", "россия", "россии", "война",
        "говорят", "собеседники", "идет", "вопросы", "почему",
    )
    legacy_russian = any(
        re.search(r"(?<![\\w])" + re.escape(word) + r"(?![\\w])",
                  current.casefold())
        for word in russian_markers
    ) or bool(re.search(r"[ыэъё]", current.casefold()))
    ukrainian_candidate = bool(re.search(r"[іїєґ]", candidate.casefold()))

    if legacy_russian and ukrainian_candidate:
        return candidate

    # An existing generic conversation label must never beat a concrete,
    # source-specific Ukrainian hook merely through title preservation.
    current_generic = "GENERIC_PRIMARY_TITLE" in _seo_editorial_preview_flags(
        current, "", (), ()
    )
    candidate_generic = "GENERIC_PRIMARY_TITLE" in _seo_editorial_preview_flags(
        candidate, "", (), ()
    )
    if current_generic and not candidate_generic:
        return candidate
    if candidate_generic and not current_generic:
        return current

    # Exact same semantic title with only punctuation/brand removed is a downgrade.
    if current_core == candidate_core:
        return current

    current_words = set(current_core.split())
    candidate_words = set(candidate_core.split())

    # If the candidate contributes no new meaningful words, keep the proven title.
    if candidate_words and candidate_words.issubset(current_words):
        return current

    return candidate




def _select_diverse_title_variants(
    primary: str, proposals: Iterable[str], *, limit: int = 3
) -> list[str]:
    """Retain strongest source-backed A/B wording without near-duplicates.

    This operates on generated text; it never fabricates an additional hook.
    """
    from difflib import SequenceMatcher

    def normalize(value: str) -> str:
        return " ".join(re.findall(r"[a-zа-яіїєґё0-9]+", value.casefold()))

    def keywords(value: str) -> set[str]:
        stop = {"що", "чому", "як", "про", "цей", "ця", "вони", "він",
                "чи", "та", "на", "до", "від", "для", "росіяни"}
        return {
            word for word in normalize(value).split()
            if len(word) >= 4 and word not in stop
        }

    retained: list[str] = []
    origin = normalize(primary)
    seen = [origin] if origin else []
    for proposal in proposals:
        title = " ".join(str(proposal or "").split())
        if not title or len(title) > 100:
            continue
        if _seo_ukrainian_language_issue(title):
            continue
        core = normalize(title)
        if not core or core in seen:
            continue
        # Near-identical punctuation, word order, or single-word substitutions
        # are not three distinctive A/B choices.
        if any(SequenceMatcher(None, core, old).ratio() >= 0.85 for old in seen):
            continue
        words = keywords(core)
        if any(
            len(words | keywords(old)) >= 3
            and len(words & keywords(old)) / len(words | keywords(old)) >= .88
            for old in seen
        ):
            continue
        retained.append(title)
        seen.append(core)
        if len(retained) == limit:
            break
    return retained

def _chapter_timestamp_seconds(value: str) -> int | None:
    parts = str(value or "").strip().split(":")
    if len(parts) not in {2, 3}:
        return None
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return None
    if any(number < 0 for number in numbers):
        return None
    if len(numbers) == 2:
        minutes, seconds = numbers
        if seconds >= 60:
            return None
        return minutes * 60 + seconds
    hours, minutes, seconds = numbers
    if minutes >= 60 or seconds >= 60:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _chapter_lines(chapters: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for raw_line in str(chapters or "").splitlines():
        line = raw_line.strip()
        match = re.match(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s+(.+?)\s*$", line)
        if not match:
            continue
        rows.append((match.group(1), match.group(2).strip()))
    return rows


def _chapters_quality_error(chapters: str, transcript: str) -> str:
    if not str(chapters or "").strip():
        return "missing_chapters"

    rows = _chapter_lines(chapters)
    if len(rows) < 3:
        return "too_few_chapters"
    if len(rows) > 12:
        return "too_many_chapters"

    allowed = {
        match.group(1)
        for match in re.finditer(
            r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]",
            str(transcript or ""),
        )
    }
    if not allowed:
        return "no_transcript_timestamps"

    seconds: list[int] = []
    for stamp, label in rows:
        sec = _chapter_timestamp_seconds(stamp)
        if sec is None:
            return "invalid_timestamp"
        if stamp not in allowed and sec != 0:
            return "unverified_timestamp"
        seconds.append(sec)

        folded = label.casefold()
        if len(label) < 4 or len(label) > 90:
            return "bad_chapter_label"
        if re.search(r"[ыэъё]", folded):
            return "chapter_wrong_language"
        russian_words = re.findall(
            r"\b(?:вступление|обсуждение|мнение|причина|причины|увольнение|"
            r"увольнения|отношения|перевод|должность|заключение|вопрос|ответы|"
            r"стратегия|коррупция|россии|путина|военной)\b",
            folded,
        )
        ukrainian_letters = len(re.findall(r"[іїєґ]", folded))
        if len(russian_words) >= 1 and ukrainian_letters == 0:
            return "chapter_wrong_language"

    if seconds[0] != 0:
        return "chapter_must_start_zero"
    if any(b <= a for a, b in zip(seconds, seconds[1:])):
        return "chapters_not_increasing"
    if any((b - a) < 10 for a, b in zip(seconds, seconds[1:])):
        return "chapters_too_close"
    return ""



def _grounded_chapters_from_transcript(
    *,
    current_title: str,
    transcript: str,
) -> str:
    """Deterministic safe chapter fallback using only verified transcript stamps."""
    title_text = str(current_title or "").casefold()
    transcript_text = str(transcript or "")
    available = {
        match.group(1)
        for match in re.finditer(
            r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]",
            transcript_text,
        )
    }
    if not available:
        return ""

    stamps = sorted(
        (
            (_chapter_timestamp_seconds(stamp), stamp)
            for stamp in available
            if _chapter_timestamp_seconds(stamp) is not None
        ),
        key=lambda item: item[0],
    )
    if not stamps:
        return ""

    if not any(seconds == 0 for seconds, _ in stamps):
        stamps.insert(0, (0, "00:00"))

    last_seconds = stamps[-1][0]
    targets = [0]
    if last_seconds >= 180:
        targets.extend(
            [
                int(last_seconds * 0.25),
                int(last_seconds * 0.50),
                int(last_seconds * 0.75),
            ]
        )
    targets.append(last_seconds)

    picked: list[tuple[int, str]] = []
    for target in targets:
        candidates = [
            item
            for item in stamps
            if not picked or item[0] >= picked[-1][0] + 10
        ]
        if not candidates:
            continue
        chosen = min(candidates, key=lambda item: abs(item[0] - target))
        if picked and chosen[0] == picked[-1][0]:
            continue
        picked.append(chosen)

    labels = (
        "Початок розмови",
        "Розвиток головної теми",
        "Думки співрозмовників",
        "Подальше обговорення",
        "Підсумок розмови",
    )
    lines = [
        f"{stamp} {labels[min(index, len(labels) - 1)]}"
        for index, (_, stamp) in enumerate(picked[:5])
    ]
    value = "\n".join(lines)
    return value if not _chapters_quality_error(value, transcript_text) else ""


def _recover_chapters_from_transcript(
    *,
    current_title: str,
    transcript: str,
    model: str,
) -> str:
    """Build conservative Ukrainian chapters using only transcript timestamps."""
    if not str(transcript or "").strip():
        return ""

    prompt = f"""
Створи таймкоди YouTube для цього відео ВИКЛЮЧНО за наданим транскриптом.

Правила:
- 6-10 глав;
- перша глава ОБОВ'ЯЗКОВО 00:00;
- використовуй лише таймкоди, які буквально є у транскрипті;
- кожна наступна глава щонайменше через 10 секунд;
- назви глав ТІЛЬКИ українською;
- назва 3-8 слів, конкретна й нейтральна;
- не вигадуй причин, висновків, посад, відносин чи подій;
- припущення співрозмовника не перетворюй на факт;
- ігноруй [музыка], [аплодисменты], лайку й ASR-сміття;
- написання ключових імен бери з назви відео;
- поверни тільки рядки формату:
00:00 Коротка українська назва

НАЗВА ВІДЕО:
{current_title}

ТРАНСКРИПТ:
{transcript[:12000]}
""".strip()

    last = ""
    for attempt in range(2):
        raw = ollama_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Ти редактор YouTube-таймкодів. "
                        "Не додавай нічого, чого немає у транскрипті."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            model=model,
            temperature=0.02,
            json_mode=False,
        )
        value = str(raw or "").strip()
        fence = chr(96) * 3
        if value.startswith(fence):
            value = value[len(fence):].lstrip()
        if value.endswith(fence):
            value = value[:-len(fence)].rstrip()
        lines: list[str] = []
        for stamp, label in _chapter_lines(value):
            lines.append(f"{stamp} {label.replace('—', '-').replace('–', '-')}")
        value = "\n".join(lines).strip()
        last = value
        if not _chapters_quality_error(value, transcript):
            return value
        prompt += (
            "\nПОПЕРЕДНІЙ ВАРІАНТ НЕ ПРОЙШОВ ПЕРЕВІРКУ. "
            "Використовуй лише точні таймкоди транскрипту і українські назви."
        )
    return last if not _chapters_quality_error(last, transcript) else ""


from .dialogue_seo import ab_title_issues, evidence_outline_text, preserve_outline_topics


def generate_seo_package_local(
    *,
    current_title: str,
    current_description: str = "",
    current_tags: list[str] | None = None,
    transcript: str = "",
    public_context: dict[str, Any] | None = None,
    is_short: bool = False,
    model: str = DEFAULT_OLLAMA_MODEL,
    fast_mode: bool = False,
    timeout: float = 300.0,
    evidence_report: dict[str, Any] | None = None,
    transcript_only_preview: bool = False,
) -> dict[str, Any]:
    context = public_context or {}
    live_profile = str(context.get("profile") or "").casefold()
    live_state = str(context.get("live_broadcast_content") or "").casefold()
    is_stream = (
        live_profile in {"live", "livestream", "stream"}
        or live_state in {"live", "upcoming", "completed"}
        or bool(context.get("is_livestream"))
    )
    verified_evidence = evidence_outline_text(evidence_report, max_chars=14000) if evidence_report else ""
    # A transcript sample is not a full-topic ranking. Explicitly tell the
    # model to avoid promoting a late isolated segment into the primary hook.
    coverage_instruction = (
        "Це лише вибірка субтитрів з різних частин відео, не повна карта тем. "
        "Не вважай останній фрагмент найважливішим. "
        "Якщо частоту чи вагу тем неможливо перевірити, не заявляй, що "
        "випадкова тема є головною; залиш редакторський перегляд. "
        "Описуй лише наявні слова співрозмовників, без висновків про результати подій."
    ) if transcript and not evidence_report else ""
    evidence_instruction = (
        "Якщо є карта фрагментів, переглянь усі теми, але в публічний "
        "опис обери лише 2–3 найсуттєвіші й пов'язані з головною назвою. "
        "Не перелічуй кожну другорядну репліку: професії, побут або "
        "випадковий жарт не є темою SEO, якщо відео переважно про інше. "
        "Три A/B формулювання, але НЕ три обов'язково різні сюжети: "
        "коли підтверджено лише один сюжет, використай різні запитання чи "
        "ракурси ТІЄЇ Ж теми. Ніколи не вигадуй третій сюжет. "
        "Це хронологічні фрагменти, а не підтверджені межі діалогів. "
        "Опис має спиратися на різні частини запису, "
        "але не мусить згадувати всі периферійні теми."
        if evidence_report else ""
    )
    prompt = f"""
Ти редактор YouTube-проєкту «РАША ГУДБАЙ». Підготуй SEO-пакет без вигадування фактів.
Використовуй ТІЛЬКИ наведений контекст. Якщо факту немає в контексті - не додавай його.

Правила:
- ЗАБОРОНЕНО абстрактні початки назв: «Проблеми», «Аналіз», «Реальність життя», «Співрозмовник обговорює», «Міркування». Назва має містити конкретне підтверджене питання, вислів чи конфлікт із субтитрів.\n- Перевір кожне слово назви, A/B і тегів: українська мова без російських кальок («доносов», «гордость», «контрактники»); не перекладай цитату так, щоб її зміст змінився.
- Заміни російські слова на українські: «контрактники» → «військові за контрактом», «доносов» → «доносів», «гордость» → «гордість». Власні назви не змінюй.
- У перших двох реченнях опису назви конкретну суперечку із субтитрів, не пиши «ми розбираємо складні теми», «учасники обговорюють проблеми» або «ключові пункти дискусії». Не оголошуй несуттєві уривки головними темами.\n- Під час вибору головної теми враховуй повторюваність і розподіл по всьому доступному відео, а не тільки фінальний уривок. За браку повної карти тем не стверджуй, що тему доведено головною.\n- основна назва та РІВНО 3 A/B формулювання українською; за браку незалежних сюжетів варіюй ракурс тієї самої підтвердженої теми, а не вигадуй нову подію;
- кожна назва до 100 символів, конкретна, зрозуміла і прив'язана до реальної теми відео;
- не копіюй поточну назву без SEO-покращення, якщо транскрипт дає точніший сильний хук;
- опис: українською, 400-900 символів змістовного тексту до службових посилань; збережи центральну тему і 2-3 ключові підтверджені деталі; решта тем лишається в окремій карті доказів;
- не копіюй назву відео як перше речення опису; перефразуй тему природною українською;
- головне джерело змісту - ТРАНСКРИПТ; назва лише задає тему, старий опис не є джерелом фактів;
- перші 1-2 речення мають назвати конкретну тему, людину/подію/питання з відео, якщо це прямо є в транскрипті;
- не розширюй імена зовнішніми знаннями: «Шойгу» не можна перетворювати на «Сергій Шойгу», якщо ім'я Сергій відсутнє в джерелі;
- ігноруй шумні/обірвані ASR-фрагменти та не перетворюй випадкові токени на назви ефірів, ЗМІ чи організацій;
- далі стисло передай 2-4 конкретні тези або позиції співрозмовників з транскрипту;
- усі твердження про зарплати, економіку, соціальні гарантії, інфраструктуру, втрати, перемоги, санкції, ціни та інші факти дозволені ЛИШЕ якщо вони прямо підтверджені транскриптом або наданим контекстом;
- якщо транскрипт суперечить старому опису, довіряй транскрипту;
- старий опис використовуй лише як технічний контекст, а не як джерело фактів;
- не пиши універсальні фрази на кшталт «учасники відповідають на запитання», «обговорюються основні теми», «дивіться повну розмову», якщо транскрипт дозволяє назвати конкретний зміст;
- не додавай загальних висновків, яких немає в транскрипті;
- припущення учасників описуй як припущення/думки, а не як встановлені факти; не вигадуй мету кадрових рішень;
- будь-які мотиви конкретних людей або пояснення кадрових рішень формулюй лише через «співрозмовник вважає/припускає», якщо це не прямо встановлений факт у джерелі;
- не додавай ENGLISH SUMMARY, англомовний дубль або переклад опису;
- без клікбейту, який не підтверджується контекстом;
- теги без #, 8-15 штук, без дублювань; конкретні запити про теми/регіони/події та формат/канал, а не штучні комбінації «війна і система», «війна і позиція», «війна і X»;
- не використовуй самостійні надто загальні теги «план», «стратегия», «политика», «должность», «перевод», «власть», «новости», якщо вони не є конкретною пошуковою фразою;
- не змінюй thumbnail;
- для Shorts не вигадуй глави;
- chapters дозволені тільки за наявності підтверджених таймкодів у транскрипті; назви глав - українською;
- поверни ТІЛЬКИ JSON з полями:
  title, title_variants, description, tags, chapters.
- chapters = "" якщо точні таймкоди неможливо підтвердити транскриптом.

SHORTS: {is_short}
СТРІМ/АРХІВ СТРІМУ: {is_stream}. Для стріму chapters ОБОВ'ЯЗКОВО порожній рядок.
ПРАВИЛА АНАЛІЗУ ПОВНОГО ВІДЕО:
{evidence_instruction}
{coverage_instruction}
КАРТА ПІДТВЕРДЖЕНИХ ТЕМ:
{verified_evidence}

ПОТОЧНА НАЗВА:
{current_title}

ПОТОЧНИЙ ОПИС:
{current_description[:1200] if evidence_report else current_description[:6000]}

ПОТОЧНІ ТЕГИ:
{json.dumps(current_tags or [], ensure_ascii=False)}

ПУБЛІЧНИЙ КОНТЕКСТ yt-dlp:
{json.dumps(context, ensure_ascii=False)[:1800] if evidence_report else json.dumps(context, ensure_ascii=False)[:6000]}

ТРАНСКРИПТ:
{('Див. підтверджену карту тем вище.' if evidence_report else transcript[:12000])}
""".strip()

    payload: dict[str, Any] = {}
    title_fallback_used = False
    last_error: Exception | None = None
    for attempt in range(1 if fast_mode else 3):
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
title: українською, до 100 символів, конкретний і підтверджений транскриптом.
title_variants: РІВНО 3 різні варіанти, кожен до 100 символів.
description: українською, 400-900 символів, головна тема і 2-3 важливі деталі з різних частин, без переліку всіх епізодів, шаблонів та ENGLISH SUMMARY.
tags: масив 8-15 конкретних пошукових фраз без # і без дублікатів; не використовуй загальні одиночні слова на кшталт план/стратегия/политика.
chapters: рядок з підтвердженими таймкодами та українськими назвами або порожній рядок.
Не вигадуй фактів. Не роби тверджень про економіку, зарплати, соцгарантії чи інші результати, якщо цього немає в транскрипті.

ПОТОЧНА НАЗВА:
{current_title}

КАРТА ПІДТВЕРДЖЕНИХ ТЕМ ВСЬОГО ВІДЕО:
{verified_evidence}

ТРАНСКРИПТ:
{('Використай карту тем вище.' if evidence_report else transcript[:8000])}
""".strip()
            raw = ollama_chat(
                [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": attempt_prompt},
                ],
                model=model,
                timeout=timeout,
                temperature=0.05 if attempt else 0.15,
                json_mode=True,
                **({"num_ctx": 16384} if evidence_report else {}),
            )
            if not isinstance(raw, str) or not raw.strip():
                # Empty successful HTTP completions are model failures, not SEO drafts.
                # The existing bounded attempt loop retries with a minimal prompt.
                raise ValueError("MODEL_EMPTY_RESPONSE_RETRY")
            candidate = _normalize_seo_candidate(_extract_json_object(raw))
            proposed_title = candidate.get("title")
            title_missing = (
                not isinstance(proposed_title, str)
                or not proposed_title.strip()
            )
            if title_missing:
                # Missing model output is not a successful SEO title generation.
                # Preserve the original metadata only for explicitly marked
                # review-only drafts; never silently treat it as approved SEO.
                existing_title = str(current_title or "").strip()
                if not existing_title and fast_mode and transcript_only_preview and transcript.strip():
                    topic_options = _grounded_review_title_variants("", transcript)
                    if topic_options:
                        existing_title = topic_options[0]
                if not existing_title:
                    raise ValueError("Немає ані назви від моделі, ані поточної назви відео. MODEL_TITLE_MISSING_NO_SAFE_FALLBACK")
                candidate["title"] = existing_title
                candidate["_fallback_review_only"] = True
                candidate["_title_generation_failure"] = "MODEL_TITLE_MISSING"
            if not str(candidate.get("title") or "").strip():
                raise ValueError("missing title")
            if not str(candidate.get("description") or "").strip():
                if fast_mode:
                    recovered_description = _grounded_description_from_transcript(
                        current_title,
                        transcript,
                    )
                else:
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
                if isinstance(item, str) and item.strip()
            ]
            if (
                len(variants_candidate) < 3
                or len({item.casefold() for item in variants_candidate[:3]}) < 3
            ):
                if fast_mode:
                    # Return an explicit review-only draft rather than losing
                    # the source-grounded title and description.
                    candidate["_fallback_review_only"] = True
                try:
                    recovered_variants = _recover_title_variants(
                        current_title=current_title,
                        # On long streams a 35k prefix is not representative.
                        # Generate hooks from source quotes across the video.
                        transcript=verified_evidence if evidence_report else transcript,
                        model=model,
                    )
                except (ValueError, RuntimeError, TimeoutError):
                    # Keep the original grounded draft if recovery fails.
                    recovered_variants = []
                # Preserve all existing distinct A/B hooks and add only
                # genuinely new recovery suggestions. A one-item recovery
                # should fill the third slot, not discard two good hooks.
                primary_key = str(candidate["title"]).strip().casefold()
                unique: list[str] = []
                used = {primary_key}
                for item in [*variants_candidate, *recovered_variants]:
                    value = str(item).strip()
                    key = value.casefold()
                    if (
                        not value or len(value) > 100 or key in used
                        or _seo_ukrainian_language_issue(value)
                    ):
                        continue
                    used.add(key)
                    unique.append(value)
                    if len(unique) == 3:
                        break
                variants_candidate = unique
                candidate["title_variants"] = variants_candidate
            variants_candidate = list(dict.fromkeys(
                item for item in variants_candidate
                if item.casefold() != str(candidate["title"]).casefold()
            ))
            if fast_mode and len(variants_candidate) < 3:
                deterministic = _grounded_review_title_variants(current_title, transcript)
                for proposed in deterministic:
                    if proposed.casefold() not in {x.casefold() for x in variants_candidate} and proposed.casefold() != str(candidate["title"]).casefold():
                        variants_candidate.append(proposed)
                    if len(variants_candidate) >= 3:
                        break
                candidate["_fallback_review_only"] = True
            candidate["title_variants"] = variants_candidate[:3]
            if evidence_report and not fast_mode:
                issues = ab_title_issues(
                    candidate["title_variants"], evidence_report,
                )
                if issues:
                    # One focused recovery using the full grounded outline.
                    # Keep the original candidates if the retry is worse.
                    try:
                        brief = _ab_distinct_evidence_brief(evidence_report)
                        targeted = (
                            "ТРИ РІЗНІ ОПОРИ З РЕАЛЬНИХ ФРАГМЕНТІВ:\n"
                            + brief + "\n"
                            + "A/B/C мають давати РІЗНІ змістові ракурси. "
                            + "Якщо у джерелі підтверджена лише одна тема, "
                            + "не вигадуй дві інші, зміни кут подачі цієї теми. "
                            + "Без вигаданих фактів.\n\n"
                            if brief else ""
                        )
                        recovered = _recover_title_variants(
                            current_title=current_title,
                            transcript=targeted + verified_evidence,
                            model=model,
                        )
                        if len(ab_title_issues(recovered, evidence_report)) < len(issues):
                            candidate["title_variants"] = recovered[:3]
                    except (ValueError, RuntimeError, TimeoutError):
                        pass
                remaining = ab_title_issues(candidate["title_variants"], evidence_report)
                if remaining:
                    independent = _recover_independent_ab_titles(
                        report=evidence_report,
                        current_title=current_title,
                        model=model,
                    )
                    if independent and len(ab_title_issues(independent, evidence_report)) < len(remaining):
                        candidate["title_variants"] = independent
                # Generic zero-network fallback: use quote-anchored topics
                # (not a model's unsupported paraphrases) before giving up.
                # This is ALWAYS marked review-only and never auto-applied.
                if ab_title_issues(candidate["title_variants"], evidence_report):
                    sourced = _verified_source_ab_titles(evidence_report, current_title)
                    if len(sourced) == 3 and not ab_title_issues(sourced, evidence_report):
                        candidate["title_variants"] = sourced
                        candidate["_source_topic_fallback_review_only"] = True
                # Never silently ship an empty A/B panel if three distinct
                # verified transcript excerpts can be recovered safely.
                if ab_title_issues(candidate["title_variants"], evidence_report):
                    safe_quotes = _source_quote_ab_titles(
                        evidence_report, current_title,
                    )
                    if safe_quotes and not ab_title_issues(safe_quotes, evidence_report):
                        candidate["title_variants"] = safe_quotes
                        candidate["ab_source_quote_fallback_used"] = True
                if ab_title_issues(candidate["title_variants"], evidence_report):
                    # The model may repeatedly hallucinate a thematic label
                    # while its verified literal quotations contain several
                    # concrete source subjects. Extract ONLY those subjects,
                    # phrased as factual-neutral Ukrainian editorial questions.
                    # Every title still passes the same strict A/B validator;
                    # this preview NEVER bypasses manual approval.
                    from .source_ab_lexical import source_grounded_ukrainian_ab
                    lexical = source_grounded_ukrainian_ab(
                        evidence_report, current_title,
                    )
                    if lexical and not ab_title_issues(lexical, evidence_report):
                        candidate["title_variants"] = lexical
                        candidate["_source_lexical_review_only"] = True
            if evidence_report and verified_evidence and (
                "GENERIC_AB_VARIANTS" in _seo_editorial_preview_flags(
                    str(candidate.get("title") or ""),
                    "",
                    candidate.get("title_variants") or [],
                    [],
                )
            ):
                # The grounding-only A/B gate accepts safe but generic
                # questions. Give the editor a focused retry anchored to
                # distinct quotations, then enforce BOTH the source gate
                # and the no-generic editorial gate.
                source_brief = _ab_distinct_evidence_brief(evidence_report)
                if source_brief:
                    try:
                        focused_ab = _recover_title_variants(
                            # The actual grounded primary hook is stronger
                            # context than the deliberately blank old title.
                            current_title=str(candidate.get("title") or current_title),
                            transcript=(
                                "ВАЖЛИВО: заборонені загальні заголовки "
                                "'Про що говорили?', 'Що кажуть співрозмовники?', "
                                "'Думки учасників розмови'. Кожен варіант "
                                "має називати КОНКРЕТНИЙ підтверджений предмет "
                                "суперечки, ім'я, місце або запитання. "
                                "Тільки із прямих цитат, без вигаданих подій.\\n"
                                + source_brief + "\\n" + verified_evidence[:8500]
                            ),
                            model=model,
                        )
                        if (
                            len(focused_ab) == 3
                            and not ab_title_issues(focused_ab, evidence_report)
                            and "GENERIC_AB_VARIANTS" not in _seo_editorial_preview_flags(
                                str(candidate.get("title") or ""), "", focused_ab, [],
                            )
                        ):
                            candidate["title_variants"] = focused_ab
                    except (ValueError, RuntimeError, TimeoutError):
                        pass
                # The model can still return vague questions after a retry.
                # Before accepting generic A/B, try purely quote-grounded
                # alternatives. They pass exactly the same source and
                # editorial-quality tests as the model proposal.
                if "GENERIC_AB_VARIANTS" in _seo_editorial_preview_flags(
                    str(candidate.get("title") or ""),
                    "", candidate.get("title_variants") or [], [],
                ):
                    from .source_ab_lexical import source_grounded_ukrainian_ab
                    source_options = [
                        source_grounded_ukrainian_ab(evidence_report, current_title),
                        _verified_source_ab_titles(evidence_report, current_title),
                        _source_quote_ab_titles(evidence_report, current_title),
                    ]
                    for proposed_ab in source_options:
                        if (
                            len(proposed_ab) == 3
                            and not ab_title_issues(proposed_ab, evidence_report)
                            and "GENERIC_AB_VARIANTS" not in _seo_editorial_preview_flags(
                                str(candidate.get("title") or ""), "", proposed_ab, [],
                            )
                        ):
                            candidate["title_variants"] = proposed_ab
                            candidate["_source_lexical_review_only"] = True
                            break
            if evidence_report:
                # The old code overwrote EVERY model-written description
                # with a short, generic keyword template, even when the
                # model had produced a concrete source-based summary.
                # Preserve substantive Ukrainian prose as a REVIEW-ONLY
                # candidate, then submit it to the independent source critic.
                description_candidate = _polish_generated_description(
                    str(candidate.get("description") or "").strip()
                )
                description_candidate = _remove_unsupported_named_claims(
                    description_candidate, evidence_report, current_title,
                )
                description_error = _description_quality_error(
                    description_candidate, transcript, max_chars=900,
                )
                if not description_error and len(description_candidate) < 400:
                    description_error = "below_editorial_target"
                if description_error:
                    # Repair the FAILED field directly, using the evidence
                    # index. Do not replace a substantive summary with the
                    # generic, repetitive deterministic template.
                    repair_prompt = (
                        "Ти український SEO-редактор. Поверни ЛИШЕ JSON "
                        "із ключем description. Перепиши ОПИС, не назву. "
                        "Створи 400–900 символів природної української "
                        "мови, 3–5 конкретних речень: тема, аргументи "
                        "співрозмовників і перевірені деталі. "
                        "Кожне твердження повинно випливати з цитат. "
                        "Не вигадуй наслідків, причин, цифр чи пов'язаних "
                        "подій. Без шаблонного вступу й заклику дивитися. "
                        "Наведені теми — пропозиції моделі, докази лише "
                        "дослівні цитати.\n"
                        "ПОМИЛКА ПОПЕРЕДНЬОГО ОПИСУ: "
                        + description_error + "\n"
                        "ПОПЕРЕДНІЙ ОПИС: " + description_candidate[:950]
                        + "\nЦИТАТИ З РІЗНИХ ЧАСТИН ВІДЕО:\n"
                        + verified_evidence[:11000]
                    )
                    try:
                        raw_repair = ollama_chat(
                            [
                                {"role": "system", "content": (
                                    "Редактор українського YouTube SEO. "
                                    "Тільки JSON без пояснень."
                                )},
                                {"role": "user", "content": repair_prompt},
                            ],
                            model=model, timeout=timeout,
                            temperature=0.1, json_mode=True,
                            num_ctx=16384,
                        )
                        repaired = _extract_json_object(raw_repair)
                        repaired_text = _polish_generated_description(
                            str(repaired.get("description") or "").strip()
                        )
                        repaired_text = _remove_unsupported_named_claims(
                            repaired_text, evidence_report, current_title,
                        )
                        repaired_issue = _description_quality_error(
                            repaired_text, transcript, max_chars=900,
                        )
                        if 400 <= len(repaired_text) <= 900 and not repaired_issue:
                            description_candidate = repaired_text
                            description_error = ""
                    except (ValueError, RuntimeError, TimeoutError, TypeError):
                        pass
                if description_error and verified_evidence:
                    # A single free-form description often stops after two
                    # sentences. Constrain the last repair to a structured
                    # sequence of five independently source-backed sentences
                    # and reject the entire result if it still misses bounds.
                    try:
                        source_notes = [
                            {
                                "time": str(block.get("start_stamp") or ""),
                                "evidence": str(topic.get("evidence") or "")[:200],
                            }
                            for block in evidence_report.get("blocks") or []
                            if isinstance(block, dict) and block.get("verified") is not False
                            for topic in (block.get("topics") or [])[:1]
                            if isinstance(topic, dict) and topic.get("evidence")
                        ][:9]
                        repair_by_sentence = (
                            "Відредагуй український SEO-опис. "
                            "ГОЛОВНА ТЕМА: " + str(candidate.get("title") or "") + ". "
                            "Відповідай ТІЛЬКИ JSON з полем sentences: "
                            "масив РІВНО П'ЯТИ змістовних українських речень. "
                            "Кожне 75–160 символів, разом 400–900 символів. "
                            "Перше речення має назвати конкретний головний "
                            "сюжет; решта чотири — лише пов'язані з ним "
                            "висловлені факти, запитання чи позиції з цитат. "
                            "Не включай сторонні епізоди про професію, "
                            "побут, хобі чи переїзд, якщо вони не пов'язані "
                            "із центральним сюжетом. "
                            "Не вигадуй дій, мотивів, причин або чисел. "
                            "Якщо джерело містить лише 2 теми, розкрий їх "
                            "двома окремими перевіреними репліками, "
                            "не вигадуй третю. Не додавай службового тексту. "
                            "Сумнівні твердження приписуй мовцю.\\n"
                            "ПОТОЧНИЙ НЕВДАЛИЙ ОПИС: " + description_candidate[:850]
                            + "\\nПІДТВЕРДЖЕНІ ЦИТАТИ:\\n"
                            + json.dumps(source_notes, ensure_ascii=False)
                        )
                        structured_raw = ollama_chat(
                            [{"role": "system", "content": (
                                "Український редактор YouTube. "
                                "Тільки JSON з п'ятьма реченнями."
                            )}, {"role": "user", "content": repair_by_sentence}],
                            model=model, timeout=timeout,
                            temperature=0.08, json_mode=True, num_ctx=8192,
                        )
                        structured_data = _extract_json_object(structured_raw)
                        sentences = structured_data.get("sentences")
                        if (
                            isinstance(sentences, list)
                            and len(sentences) == 5
                            and all(isinstance(x, str) and len(x.strip()) >= 50
                                    for x in sentences)
                        ):
                            structured_text = _polish_generated_description(
                                " ".join(x.strip() for x in sentences)
                            )
                            structured_text = _remove_unsupported_named_claims(
                                structured_text, evidence_report, current_title,
                            )
                            if (
                                400 <= len(structured_text) <= 900
                                and not _description_quality_error(
                                    structured_text, transcript, max_chars=900,
                                )
                            ):
                                description_candidate = structured_text
                                description_error = ""
                    except (RuntimeError, ValueError, TimeoutError, TypeError):
                        pass
                if description_error:
                    # Keep the failed wording in the editor-only draft and
                    # let the quality gate reject it. Never pad with boilerplate
                    # simply to reach 400 characters.
                    candidate["description"] = description_candidate
                    candidate["_description_quality_issue"] = description_error
                else:
                    candidate["description"] = description_candidate
                    candidate["_source_model_description_review_only"] = True
            else:
                description_candidate = _polish_generated_description(
                    str(candidate.get("description") or "").strip()
                )
                if evidence_report:
                    description_candidate = _remove_unsupported_named_claims(
                        description_candidate, evidence_report, current_title,
                    )
                candidate["description"] = description_candidate
                description_error = _description_quality_error(
                    description_candidate,
                    transcript,
                    **({"max_chars": 950} if evidence_report else {}),
                )
                if transcript.strip():
                    if fast_mode:
                        if description_error:
                            fallback_description = _grounded_description_from_transcript(
                                current_title,
                                transcript,
                            )
                            candidate["description"] = fallback_description
                            description_candidate = fallback_description
                            description_error = _description_quality_error(
                                description_candidate,
                                transcript,
                                **({"max_chars": 950} if evidence_report else {}),
                            )
                    elif description_error:
                        # Only pay for a repair pass when the candidate actually
                        # fails quality checks. The old implementation made extra
                        # Ollama requests even for an already valid description.
                        recovered_description = _recover_missing_description(
                            current_title=current_title,
                            transcript=transcript,
                            public_context=context,
                            model=model,
                        )
                        if recovered_description:
                            candidate["description"] = recovered_description
                            description_candidate = recovered_description
                            description_error = _description_quality_error(
                                description_candidate,
                                transcript,
                                **({"max_chars": 950} if evidence_report else {}),
                            )
                        if description_error:
                            fallback_description = _grounded_description_from_transcript(
                                current_title,
                                transcript,
                            )
                            candidate["description"] = fallback_description
                            description_candidate = fallback_description
                            description_error = _description_quality_error(
                                description_candidate,
                                transcript,
                                **({"max_chars": 950} if evidence_report else {}),
                            )
                if transcript.strip() and description_error:
                    raise ValueError(
                        "description quality failed: " + description_error
                    )

            model_tags = [
                str(item).strip().lstrip("#")
                for item in (candidate.get("tags") or [])
                if str(item).strip()
                and not _seo_ukrainian_language_issue(str(item))
                and _tag_is_grounded(
                    str(item),
                    current_title,
                    transcript,
                )
            ]
            grounded_tags = _grounded_tags_from_transcript(
                current_title,
                transcript,
            )
            merged_tags: list[str] = []
            seen_tags: set[str] = set()

            primary_tags = model_tags if evidence_report and transcript.strip() else grounded_tags
            fallback_tags = grounded_tags if evidence_report and transcript.strip() else model_tags
            # Search phrases describing a verified episode topic are more
            # useful than a wall of one-word keywords. Keep proper names and
            # channel tags, but choose specific multiword queries first.
            if evidence_report and transcript.strip():
                channel = {"раша гудбай", "чат рулетка"}
                primary_tags = sorted(
                    primary_tags,
                    key=lambda item: (
                        str(item).casefold() in channel,
                        len(str(item).split()) < 2,
                        -min(len(str(item).split()), 5),
                    ),
                )

            for item in primary_tags:
                key = item.casefold()
                if not key or key in seen_tags:
                    continue
                seen_tags.add(key)
                merged_tags.append(item)
                if len(merged_tags) >= 10:
                    break

            if len(merged_tags) < 8:
                for item in fallback_tags:
                    key = item.casefold()
                    if not key or key in seen_tags:
                        continue
                    seen_tags.add(key)
                    merged_tags.append(item)
                    if len(merged_tags) >= 10:
                        break

            generic_search_tags = {
                "раша гудбай", "чат рулетка", "чат рулетка з росіянами",
                "росія", "росіяни", "думки росіян",
                "опитування росіян", "реакція росіян",
                "запитання росіянам", "розмова з росіянами",
                "youtube", "новини",
            }
            # Do not let the model's generic one-word filler consume the
            # ten available search-tag slots. Keep literal named entities
            # only if they are mentioned in the transcript.
            if evidence_report and transcript.strip():
                format_tags = {"раша гудбай", "чат рулетка"}
                merged_tags = [
                    tag for tag in merged_tags
                    if (
                        len(tag.split()) >= 2
                        or tag.casefold() in format_tags
                        or (
                            tag.casefold() in {
                                "путін", "шойгу", "мобілізація",
                                "вибори", "санкції", "пропаганда",
                            }
                            and _tag_is_grounded(tag, current_title, transcript)
                        )
                    )
                ]
                seen_tags = {tag.casefold() for tag in merged_tags}
            topical_count = sum(
                tag.casefold() not in generic_search_tags
                for tag in merged_tags
            )
            if evidence_report and verified_evidence and (
                len(merged_tags) < 8 or topical_count < 4
            ):
                # If the model filled all slots with channel/format tags,
                # reclaim those slots for episode-specific search queries.
                if topical_count < 4:
                    merged_tags = [
                        tag for tag in merged_tags
                        if tag.casefold() not in generic_search_tags
                        or tag.casefold() in {"раша гудбай", "чат рулетка"}
                    ]
                    seen_tags = {tag.casefold() for tag in merged_tags}
                # Repair tag QUALITY at the generator, not at the acceptance
                # gate. Ask for specific episode search terms grounded in
                # verified quotations, then check each candidate against the
                # complete SRT before adding it.
                tag_prompt = (
                    "Ти SEO-редактор українського YouTube. Поверни JSON "
                    'з полем "tags": масив 8–12 українських пошукових '
                    "фраз без #. Візьми конкретні імена, місця, питання й "
                    "теми лише з ЦИТАТ. Не з'єднуй слова з різних діалогів, "
                    "не додавай нові події, причини, цифри або загальні "
                    "теги на кшталт новини/суспільство. Віддавай перевагу "
                    "природним фразам із 2–5 слів, не вигадуй тему, "
                    "щоб набрати 8 тегів.\n"
                    "УЖЕ Є: " + json.dumps(merged_tags, ensure_ascii=False)
                    + "\nЦИТАТИ З РІЗНИХ ЧАСТИН ВІДЕО:\n"
                    + verified_evidence[:10500]
                )
                try:
                    tag_raw = ollama_chat(
                        [
                            {"role": "system", "content": (
                                "Українські тематичні пошукові фрази. Лише JSON."
                            )},
                            {"role": "user", "content": tag_prompt},
                        ],
                        model=model, timeout=timeout,
                        temperature=0.08, json_mode=True, num_ctx=16384,
                    )
                    tag_reply = _extract_json_object(tag_raw)
                    proposals = tag_reply.get("tags")
                    if isinstance(proposals, list):
                        for proposed in proposals[:24]:
                            tag = " ".join(str(proposed or "").split()).lstrip("#")
                            key = tag.casefold()
                            if (
                                not tag or len(tag) > 70 or key in seen_tags
                                or (len(tag.split()) < 2 and not (
                                    tag[:1].isupper() and key not in {"росія", "україна", "новини"}
                                ))
                                or _seo_ukrainian_language_issue(tag)
                                or not _tag_is_grounded(
                                    tag, current_title, transcript,
                                )
                            ):
                                continue
                            seen_tags.add(key)
                            merged_tags.append(tag)
                            if len(merged_tags) >= 12:
                                break
                except (ValueError, RuntimeError, TimeoutError, TypeError):
                    # A failed optional tag rewrite must never erase a
                    # still-useful, explicitly unapproved draft.
                    pass
            topical_count = sum(
                tag.casefold() not in generic_search_tags
                for tag in merged_tags
            )
            if len(merged_tags) < 8 or topical_count < 3:
                # Eight generic brand/format tags are NOT successful SEO.
                # Keep the draft, but record poor topical coverage honestly.
                candidate["_tags_review_required"] = True
            candidate["tags"] = merged_tags

            payload = candidate
            title_fallback_used = title_missing
            break
        except (ValueError, RuntimeError, TimeoutError) as exc:
            last_error = exc
            # Model outage is not an SEO formatting defect. Stop retries
            # immediately instead of requesting the same broken endpoint.
            cause = getattr(exc, "__cause__", None)
            if isinstance(cause, urllib.error.HTTPError) and cause.code >= 500:
                break
    if not payload and evidence_report and not fast_mode and str(current_title).strip():
        # A verified transcript is valuable even when the model or editorial
        # rules cannot finish a complete SEO package. Preserve a review-only
        # draft, NEVER silently mark it safe and NEVER post to YouTube.
        verified_topics = [
            topic for block in evidence_report.get("blocks") or []
            if isinstance(block, dict) and block.get("verified") is not False
            for topic in block.get("topics") or []
            if isinstance(topic, dict) and str(topic.get("evidence") or "").strip()
        ]
        if verified_topics:
            review_topics: list[str] = []
            try:
                safe_description = _deterministic_evidence_description(
                    current_title, evidence_report,
                    review_unmapped=review_topics,
                )
            except ValueError:
                # No verified public subject could be mapped, so never
                # substitute an unchecked LLM narrative for public claims.
                # This text exists ONLY as an unapproved local draft.
                safe_description = (
                    "Це попередній SEO-чернетковий опис для перевірки редактором. "
                    "У відео є розмови співрозмовників, але автоматична система "
                    "не змогла надійно підтвердити формулювання ключових тем. "
                    "Потрібно звірити твердження з оригінальним записом і "
                    "уточнити зміст перед публікацією. "
                    "Назву, тематичні акценти та пошукові фрази слід "
                    "перевірити вручну за наявною картою цитат."
                )
                review_topics.append("unmapped_evidence")
            from .source_ab_lexical import source_grounded_ukrainian_ab
            payload = {
                "title": str(current_title).strip(),
                "title_variants": (
                    source_grounded_ukrainian_ab(
                        evidence_report, current_title,
                    )
                    or _verified_source_ab_titles(
                        evidence_report, current_title,
                    )
                ),
                "description": safe_description,
                "tags": _grounded_tags_from_transcript(current_title, transcript)[:10],
                "chapters": "",
                "_deterministic_editor": True,
                "_fallback_review_only": True,
                "evidence_editorial_review": review_topics,
                "_description_quality_issue": "editorial_review_required",
            }
            title_fallback_used = True
    if not payload and fast_mode and transcript_only_preview and transcript.strip():
        # Isolated QA only: an invalid model reply must not stop collecting
        # technical diagnostics. Generate neutral source-topic review prompts.
        # These are never verified titles and are never publication-ready.
        qa_titles = _grounded_review_title_variants("", transcript, pool_size=4)
        if qa_titles:
            payload = {
                "title": qa_titles[0],
                "title_variants": qa_titles[1:],
                "description": _grounded_description_from_transcript("", transcript),
                "tags": _grounded_tags_from_transcript("", transcript)[:10],
                "chapters": "",
                "_fallback_review_only": True,
            }
            title_fallback_used = True
    if not payload:
        mode_text = "швидкого проходу" if fast_mode else "повторів"
        raise ValueError(
            "Локальна SEO-генерація не пройшла валідацію після "
            f"{mode_text}: {last_error}"
        )

    title = str(payload.get("title") or "").strip()
    title = _preserve_current_title_when_candidate_is_not_stronger(
        current_title,
        title,
    )
    if fast_mode:
        title = _clean_project_title_for_seo(title)
    # Improve the PRIMARY headline instead of settling for a generic
    # "what do Russians think" title while valid concrete evidence exists.
    # This is generation, not an extra diagnostic pass.
    if (
        evidence_report and verified_evidence
        and "GENERIC_PRIMARY_TITLE" in _seo_editorial_preview_flags(
            title, "", (), ()
        )
    ):
        specific_title_prompt = (
            "Напиши ОДНУ конкретну українську назву YouTube, "
            "40–95 символів. Перша частина назви має чітко називати "
            "подію, людину, факт розмови або конкретне запитання. "
            "НЕ використовуй загальні заголовки про думки росіян, "
            "чат-рулетку або співрозмовників. "
            "Не вигадуй невисловлених фактів, імен та причин. "
            'Поверни лише JSON {"title":"..."}.'
            "\nПОПЕРЕДНЯ СЛАБКА НАЗВА: " + title
            + "\nЦИТАТИ ІЗ ВІДЕО:\n" + verified_evidence[:11000]
        )
        try:
            specific_raw = ollama_chat(
                [
                    {"role": "system", "content": (
                        "Точний український редактор SEO. Лише JSON."
                    )},
                    {"role": "user", "content": specific_title_prompt},
                ],
                model=model, timeout=timeout,
                temperature=0.1, json_mode=True, num_ctx=16384,
            )
            specific_data = _extract_json_object(specific_raw)
            proposed_title = str(specific_data.get("title") or "").strip()
            if (
                30 <= len(proposed_title) <= 100
                and not _seo_ukrainian_language_issue(proposed_title)
                and not _seo_title_source_conflicts(
                    proposed_title, transcript
                )
                and "GENERIC_PRIMARY_TITLE" not in _seo_editorial_preview_flags(
                    proposed_title, "", (), ()
                )
            ):
                title = proposed_title
                payload["_primary_title_repaired"] = True
        except (ValueError, RuntimeError, TimeoutError, TypeError):
            pass
    unchanged_title = bool(
        str(current_title or "").strip()
        and title.casefold() == str(current_title or "").strip().casefold()
    )
    variants = [
        _clean_project_title_for_seo(str(item).strip())
        if fast_mode
        else str(item).strip()
        for item in (payload.get("title_variants") or [])
        if str(item).strip()
    ]
    description = _polish_generated_description(
        str(payload.get("description") or "").strip()
    )
    omitted_topics: list[str] = []
    if evidence_report and not payload.get("_deterministic_editor"):
        # Keep the 400-900-character public description intact. Appending up
        # to 50 AI-labelled "verified topics" broke the SEO length gate and
        # promoted model topic labels into user-facing factual claims.
        # Record unsupported/omitted subjects separately for editorial QA.
        description, omitted_topics = preserve_outline_topics(
            description, evidence_report,
            max_topic_bullets=0,
            max_body_bytes=900,
        )
    if evidence_report and verified_evidence:
        varied = _select_diverse_title_variants(title, variants)
        if len(varied) < 3 and not fast_mode:
            # Regenerate only missing A/B angles; do not overwrite a strong
            # primary headline and do not invent any third dialogue.
            try:
                fresh = _recover_title_variants(
                    current_title=title,
                    transcript=verified_evidence,
                    model=model,
                )
                varied = _select_diverse_title_variants(
                    title, [*varied, *fresh],
                )
            except (ValueError, RuntimeError, TimeoutError):
                pass
        variants = varied
    # A quote-root validator can accept a hollow question such as
    # "Мобілізація: про що йдеться у чат-рулетці?". In that case repair
    # the FINAL A/B output, not an intermediate candidate that later
    # source fallbacks may silently replace with the same generic frames.
    if evidence_report and verified_evidence and not fast_mode:
        if "GENERIC_AB_VARIANTS" in _seo_editorial_preview_flags(
            title, "", variants, (),
        ):
            try:
                brief = _ab_distinct_evidence_brief(evidence_report)
                prompt_ab = (
                    "Ти головний редактор українського YouTube-каналу. "
                    "Заміни ТРИ слабкі A/B-заголовки на три КОНКРЕТНІ "
                    "історії з підтверджених цитат. Не повторюй назву. "
                    "ЗАБОРОНЕНО: 'що говорять співрозмовники', 'про що "
                    "йдеться', 'що прозвучало', 'думки учасників', "
                    "'розмова про', 'питання про'. Кожен заголовок "
                    "має містити підтверджену ДІЮ, ПИТАННЯ, ЦИТАТУ "
                    "або протиставлення, а не лише слово-ярлик. "
                    "Будь-яке твердження приписуй учаснику розмови. "
                    "Не вигадуй мотивів, чисел, подій, висновків "
                    "або зв'язків між різними діалогами. "
                    "Поверни тільки JSON з рівно 3 title_variants, "
                    "кожен 35–95 символів українською.\\n"
                    "ГОЛОВНИЙ ЗАГОЛОВОК: " + title
                    + "\\nСЛАБКІ ВАРІАНТИ: "
                    + json.dumps(variants, ensure_ascii=False)
                    + "\\nТРИ РІЗНІ ДОСЛІВНІ ОПОРИ:\\n" + brief
                    + "\\nПЕРЕВІРЕНІ ЦИТАТИ:\\n" + verified_evidence[:11000]
                )
                raw_ab = ollama_chat(
                    [{"role": "system", "content": (
                        "Редактор конкретних українських YouTube-заголовків. "
                        "Поверни тільки JSON, без загальних тем."
                    )}, {"role": "user", "content": prompt_ab}],
                    model=model, timeout=timeout,
                    temperature=0.12, json_mode=True, num_ctx=16384,
                )
                data_ab = _normalize_seo_candidate(_extract_json_object(raw_ab))
                proposed = [str(v).strip() for v in (
                    data_ab.get("title_variants") or []
                ) if isinstance(v, str) and str(v).strip()]
                payload["_ab_specific_diagnostic"] = {
                    "candidates": proposed,
                    "source_issues": ab_title_issues(proposed, evidence_report),
                    "quality_flags": _seo_editorial_preview_flags(
                        title, "", proposed, (),
                    ),
                    "language_issues": [
                        bool(_seo_ukrainian_language_issue(v)) for v in proposed
                    ],
                }
                if len(proposed) == 3 and (
                    ab_title_issues(proposed, evidence_report)
                    or "GENERIC_AB_VARIANTS" in _seo_editorial_preview_flags(
                        title, "", proposed, (),
                    )
                ):
                    # The first model pass often paraphrases a fact using
                    # an unsupported new verb. Supply the exact rejected
                    # wording and source objections for ONE bounded repair.
                    try:
                        verified_quotes = [
                            str(item.get("evidence") or "")[:200]
                            for block in evidence_report.get("blocks") or []
                            if isinstance(block, dict) and block.get("verified") is not False
                            for item in (block.get("topics") or [])[:1]
                            if isinstance(item, dict) and item.get("evidence")
                        ][:10]
                        repair_ab_prompt = (
                            "Виправ ТРИ українські A/B-назви за точними "
                            "цитатами. Кожна 35–95 символів, конкретна, "
                            "із різною змістовою опорою. Попередні фрази "
                            "містять непідтверджені слова. Пиши так, щоб "
                            "всі змістові дії й події були прямо видимі "
                            "у дослівних цитатах. НЕ додавай дієслів "
                            "'висміяв', 'примусив', 'викрив', 'довів', "
                            "'розгромив', якщо це не сказано в цитаті. "
                            "Можна передати дослівну російську репліку "
                            "українською зі збереженням сенсу та атрибуції. "
                            "Не використовуй шаблонів 'що говорять', "
                            "'що прозвучало', 'про що йдеться'. "
                            "JSON: title_variants, рівно три рядки.\\n"
                            "ПОПЕРЕДНІ: " + json.dumps(proposed, ensure_ascii=False)
                            + "\\nПОМИЛКИ ПЕРЕВІРКИ: " + json.dumps(
                                ab_title_issues(proposed, evidence_report),
                                ensure_ascii=False,
                            )
                            + "\\nДОСЛІВНІ ЦИТАТИ: " + json.dumps(
                                verified_quotes, ensure_ascii=False,
                            )
                        )
                        corrected_raw = ollama_chat(
                            [{"role": "system", "content": (
                                "Суворий український фактчекер заголовків. Лише JSON."
                            )}, {"role": "user", "content": repair_ab_prompt}],
                            model=model, timeout=timeout,
                            temperature=0.05, json_mode=True, num_ctx=8192,
                        )
                        corrected_data = _normalize_seo_candidate(
                            _extract_json_object(corrected_raw)
                        )
                        corrected = [
                            str(v).strip() for v in (
                                corrected_data.get("title_variants") or []
                            ) if isinstance(v, str) and v.strip()
                        ]
                        payload["_ab_specific_diagnostic"]["correction"] = corrected
                        payload["_ab_specific_diagnostic"]["correction_issues"] = (
                            ab_title_issues(corrected, evidence_report)
                        )
                        # Verbatim Russian speech is good evidence, but
                        # Ukrainian SEO needs faithful Ukrainian rendering.
                        # Translate only SOURCE-GROUNDED corrected headlines,
                        # without adding words, causes or new events.
                        if (
                            len(corrected) == 3
                            and any(_seo_ukrainian_language_issue(v) for v in corrected)
                        ):
                            try:
                                translation_prompt = (
                                    "Переклади ці три заголовки ПОВНІСТЮ "
                                    "українською. Збережи кожну цитату, "
                                    "заперечення, особу й сенс; не доповнюй "
                                    "фактів і не вигадуй дій чи причин. "
                                    "Власні назви українською. "
                                    "Без російських слів навіть у лапках. "
                                    "JSON: title_variants, рівно 3 рядки.\\n"
                                    + json.dumps(corrected, ensure_ascii=False)
                                )
                                translated_raw = ollama_chat(
                                    [{"role": "system", "content": (
                                        "Професійний перекладач російської "
                                        "на українську. Лише JSON."
                                    )}, {"role": "user", "content": translation_prompt}],
                                    model=model, timeout=timeout, temperature=0.0,
                                    json_mode=True, num_ctx=4096,
                                )
                                translated_data = _normalize_seo_candidate(
                                    _extract_json_object(translated_raw)
                                )
                                translated = [
                                    str(v).strip() for v in (
                                        translated_data.get("title_variants") or []
                                    ) if isinstance(v, str) and v.strip()
                                ]
                                payload["_ab_specific_diagnostic"]["translation"] = translated
                                payload["_ab_specific_diagnostic"]["translation_issues"] = (
                                    ab_title_issues(translated, evidence_report)
                                )
                                if len(translated) == 3:
                                    corrected = translated
                            except (RuntimeError, ValueError, TimeoutError, TypeError):
                                pass
                        if (
                            len(corrected) == 3
                            and all(35 <= len(v) <= 95 for v in corrected)
                            and not any(_seo_ukrainian_language_issue(v) for v in corrected)
                            and not ab_title_issues(corrected, evidence_report)
                            and "GENERIC_AB_VARIANTS" not in _seo_editorial_preview_flags(
                                title, "", corrected, (),
                            )
                            and len(_select_diverse_title_variants(title, corrected)) == 3
                        ):
                            proposed = corrected
                    except (RuntimeError, ValueError, TimeoutError, TypeError):
                        pass
                if (
                    len(proposed) == 3
                    and all(35 <= len(v) <= 95 for v in proposed)
                    and not any(_seo_ukrainian_language_issue(v) for v in proposed)
                    and not ab_title_issues(proposed, evidence_report)
                    and "GENERIC_AB_VARIANTS" not in _seo_editorial_preview_flags(
                        title, "", proposed, (),
                    )
                    and len(_select_diverse_title_variants(title, proposed)) == 3
                ):
                    variants = proposed
                    payload["_final_ab_specific_repaired"] = True
            except (RuntimeError, ValueError, TimeoutError, TypeError) as exc:
                payload["_ab_specific_diagnostic"] = {
                    "error_type": type(exc).__name__,
                }
    if (
        evidence_report and verified_evidence and not fast_mode
        and "GENERIC_AB_VARIANTS" in _seo_editorial_preview_flags(
            title, "", variants, (),
        )
    ):
        # Last source-grounded alternative: three compact Ukrainian
        # translations of literal source quotations, without generic
        # question frames or new narrative verbs. The same strict source,
        # language, duplicate and editorial gates still apply.
        try:
            source_quotes = [
                {
                    "time": str(block.get("start_stamp") or ""),
                    "quote": str(topic.get("evidence") or "")[:230],
                }
                for block in evidence_report.get("blocks") or []
                if isinstance(block, dict) and block.get("verified") is not False
                for topic in (block.get("topics") or [])[:1]
                if isinstance(topic, dict) and topic.get("evidence")
            ][:16]
            if len(source_quotes) >= 3:
                quote_prompt = (
                    "Створи РІВНО 3 різні YouTube A/B-заголовки "
                    "УКРАЇНСЬКОЮ, кожен лише як КОРОТКА ДОСЛІВНА "
                    "цитата мовця в перекладі з російської. "
                    "Без вигаданих дій, тлумачень, причин і наслідків. "
                    "Вибери три різні змістовні репліки, найближчі "
                    "до ОСНОВНОГО заголовка; не вибирай професії, "
                    "побутові подробиці або випадкові фрази, "
                    "якщо основна тема політична. "
                    "Усе всередині лапок має бути точною передачею "
                    "слів, а не вільним переказом. "
                    "Довжина кожного 25–85 символів. "
                    "Не використовуй слова 'що говорять', "
                    "'про що йдеться', 'що прозвучало'. "
                    "Без російської мови навіть у цитатах. "
                    "JSON: {title_variants: [три рядки]}.\\n"
                    "ГОЛОВНИЙ ЗАГОЛОВОК: " + title
                    + "\\nПІДТВЕРДЖЕНІ ДОСЛІВНІ РЕПЛІКИ: "
                    + json.dumps(source_quotes, ensure_ascii=False)
                )
                quote_raw = ollama_chat(
                    [{"role": "system", "content": (
                        "Український перекладач реальних цитат. "
                        "Без домислів. Лише JSON."
                    )}, {"role": "user", "content": quote_prompt}],
                    model=model, timeout=timeout,
                    temperature=0.0, json_mode=True, num_ctx=8192,
                )
                quote_data = _normalize_seo_candidate(_extract_json_object(quote_raw))
                quote_ab = [
                    str(item).strip()
                    for item in (quote_data.get("title_variants") or [])
                    if isinstance(item, str) and item.strip()
                ]
                payload["_quote_ab_diagnostic"] = {
                    "candidates": quote_ab,
                    "source_issues": ab_title_issues(quote_ab, evidence_report),
                    "quality_flags": _seo_editorial_preview_flags(
                        title, "", quote_ab, (),
                    ),
                }
                if (
                    len(quote_ab) == 3
                    and all(25 <= len(v) <= 85 for v in quote_ab)
                    and not any(_seo_ukrainian_language_issue(v) for v in quote_ab)
                    and not ab_title_issues(quote_ab, evidence_report)
                    and "GENERIC_AB_VARIANTS" not in _seo_editorial_preview_flags(
                        title, "", quote_ab, (),
                    )
                    and len(_select_diverse_title_variants(title, quote_ab)) == 3
                ):
                    variants = quote_ab
                    payload["_source_quote_fallback_review_only"] = True
        except (RuntimeError, ValueError, TimeoutError, TypeError):
            pass
    title_issues = ab_title_issues(variants, evidence_report)
    source_quote_fallback = bool(payload.get("ab_source_quote_fallback_used"))
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

    if not is_short and not is_stream and transcript.strip():
        chapter_error = _chapters_quality_error(chapters, transcript)
        if chapter_error and not fast_mode:
            try:
                chapters = _recover_chapters_from_transcript(
                    current_title=current_title,
                    transcript=transcript,
                    model=model,
                )
            except (RuntimeError, TimeoutError, ValueError):
                # The chapter model is optional. An outage must not erase
                # a verified, review-only SEO package for the whole video.
                chapters = ""
        if not chapters or _chapters_quality_error(chapters, transcript):
            chapters = _grounded_chapters_from_transcript(
                current_title=current_title,
                transcript=transcript,
            )
        if chapters and _chapters_quality_error(chapters, transcript):
            chapters = ""
        # Generic timestamps are not real dialogue chapters, regardless of mode.
        if chapters and _chapters_are_generic(chapters):
            chapters = ""

    if not title:
        raise ValueError("Локальна модель не створила назву.")
    if len(title) > 100:
        raise ValueError("Локальна модель створила назву довшу за 100 символів.")
    if not description:
        raise ValueError("Локальна модель не створила опис.")
    if len(description) > (3900 if evidence_report else 5000):
        raise ValueError("SEO-опис перевищує безпечний ліміт; збережено карту доказів без втрати тем.")
    if is_short or is_stream:
        chapters = ""

    # A historical Russian filename is not suitable Ukrainian SEO metadata.
    # In fast preview mode, prefer an already generated Ukrainian heading.
    # This is a review-only substitution, never an automatic publication.
    if fast_mode and _seo_ukrainian_language_issue(title):
        safe_headings = [
            item for item in variants
            if item and len(item) <= 100 and not _seo_ukrainian_language_issue(item)
        ]
        if safe_headings:
            title = safe_headings[0]
            variants = [item for item in variants if item.casefold() != title.casefold()]
            for option in _grounded_review_title_variants(current_title, transcript):
                if (option.casefold() != title.casefold()
                    and option.casefold() not in {v.casefold() for v in variants}
                    and not _seo_ukrainian_language_issue(option)):
                    variants.append(option)
                if len(variants) >= 3:
                    break
            variants = variants[:3]
            payload["_fallback_review_only"] = True

    # Remove Russian A/B candidates before preview approval. Fill missing slots
    # only from topics explicitly detected in the source. Unproven drafts stay
    # review-only and may contain fewer than three options.
    if fast_mode:
        from .seo_quality_gate import sanitize_review_variants

        variants, variants_changed = sanitize_review_variants(
            title,
            variants,
            _grounded_review_title_variants(current_title, transcript, pool_size=4),
        )
        if variants_changed:
            payload["_fallback_review_only"] = True
        variants, overlap_improved = _improve_review_ab_distinctness(
            title, variants, transcript, evidence_report,
        )
        if overlap_improved:
            payload["_fallback_review_only"] = True
        # Recheck the final list, not the discarded model variants.
        title_issues = ab_title_issues(variants, evidence_report)

    # The source map covers the whole stream, but public SEO should focus
    # on the actual headline subject, not append every unrelated small-talk
    # fragment. Select literal notes with the largest title-topic overlap.
    if evidence_report and verified_evidence and not fast_mode:
        try:
            from .dialogue_seo import _cross_language_topic_word
            title_roots = {
                _cross_language_topic_word(word)[:5]
                for word in re.findall(r"[a-zа-яёіїєґ]{5,}", title.casefold())
            }
            source_notes = []
            for block in evidence_report.get("blocks") or []:
                if not isinstance(block, dict) or block.get("verified") is False:
                    continue
                for item in (block.get("topics") or [])[:1]:
                    if not isinstance(item, dict) or not item.get("evidence"):
                        continue
                    quote = str(item["evidence"])[:230]
                    quote_roots = {
                        _cross_language_topic_word(word)[:5]
                        for word in re.findall(
                            r"[a-zа-яёіїєґ]{5,}", quote.casefold(),
                        )
                    }
                    overlap = len(title_roots & quote_roots)
                    source_notes.append({
                        "time": str(block.get("start_stamp") or ""),
                        "quote": quote,
                        "score": overlap,
                    })
            # Always include the best headline-related evidence. Only use
            # adjacent themes as supporting details, never claim all source
            # fragments are equally central.
            ranked_notes = sorted(
                source_notes, key=lambda item: -item["score"],
            )[:5]
            if ranked_notes:
                focused_prompt = (
                    "Напиши точний SEO-опис УКРАЇНСЬКОЮ на 400–900 "
                    "символів. Чотири–п'ять речень, зв'язний текст. "
                    "Використовуй тільки ДОСЛІВНІ цитати з короткого "
                    "списку. Це кілька РІЗНИХ учасників: не приписуй "
                    "їхні суперечливі висловлювання одній особі. "
                    "Центральна тема визначається заголовком, а не "
                    "хронологічним порядком цитат. Не пиши про "
                    "другорядні побутові подробиці чи професії, "
                    "якщо вони не стосуються центральної теми. "
                    "Заявлені факти подавай як слова учасника, "
                    "не як незалежно доведену подію. "
                    "Ніяких вигаданих наслідків, мотивів, "
                    "викриттів, цифр і нових людей. "
                    "Поверни тільки JSON з ключем description.\\n"
                    "ГОЛОВНИЙ ЗАГОЛОВОК: " + title
                    + "\\nЦИТАТИ: " + json.dumps(
                        ranked_notes, ensure_ascii=False,
                    )
                )
                focused_raw = ollama_chat(
                    [{"role": "system", "content": (
                        "Доказовий український SEO-редактор. Лише JSON."
                    )}, {"role": "user", "content": focused_prompt}],
                    model=model, timeout=timeout, temperature=0.07,
                    json_mode=True, num_ctx=8192,
                )
                focused_data = _extract_json_object(focused_raw)
                focused_description = _polish_generated_description(
                    str(focused_data.get("description") or "").strip()
                )
                focused_description = _remove_unsupported_named_claims(
                    focused_description, evidence_report, current_title,
                )
                if (
                    400 <= len(focused_description) <= 900
                    and not _seo_ukrainian_language_issue(focused_description)
                    and not _description_quality_error(
                        focused_description, transcript, max_chars=900,
                    )
                ):
                    description = focused_description
                    payload.pop("_description_quality_issue", None)
                    payload["_focused_description_repaired"] = True
        except (RuntimeError, ValueError, TimeoutError, TypeError):
            pass

    editorial_quality_flags = _seo_editorial_preview_flags(
        title, description, variants, tags,
    )
    # The field-specific description repair must not silently pass after
    # unsuccessful rewrite just because its character count happens to fit.
    if payload.get("_description_quality_issue"):
        editorial_quality_flags.append("DESCRIPTION_QUALITY_UNRESOLVED")
    # Validate the PROPOSED title as well as the existing one. Only checking
    # the existing title hid unsupported names newly invented by the model.
    # These are review warnings, never grounds for auto-publishing.
    source_alignment_conflicts = _seo_title_source_conflicts(
        str(current_title or "").strip(), transcript
    )
    generated_conflicts = _seo_title_source_conflicts(title, transcript)
    editorial_quality_flags.extend(source_alignment_conflicts)
    editorial_quality_flags.extend(
        "GENERATED_" + issue for issue in generated_conflicts
    )
    # In transcript-only QA the historical title is intentionally blank.
    # Its absence is not a factual defect when quote-verified source exists.
    if not transcript.strip() or (
        not str(current_title or "").strip() and not evidence_report
    ):
        editorial_quality_flags.append("TITLE_SRT_ALIGNMENT_UNVERIFIED")
    editorial_quality_flags = list(dict.fromkeys(editorial_quality_flags))
    from .seo_quality_gate import inspect_package, inspect_editorial_targets
    qa_inputs = {
        "title": title,
        "title_variants": variants[:3],
        "description": description,
        "tags": tags[:15],
    }
    format_gate = inspect_package(qa_inputs)
    editorial_gate = inspect_editorial_targets(qa_inputs)

    # A second, independent local model pass checks facts against source notes.
    # Never allow this pass to grant publication approval.
    reviewer_report = {
        "review_status": "SOURCE_NOT_AVAILABLE", "issues": [],
        "editorial_approved": False, "publication_allowed": False,
    }
    notes = []
    if evidence_report and isinstance(evidence_report.get("blocks"), list):
        from .seo_editorial_reviewer import (
            review_seo_candidate, select_independent_source_notes,
        )
        notes = select_independent_source_notes(
            evidence_report, max_blocks=24, max_notes=40,
        )
        if notes:
            reviewer_report = review_seo_candidate(
                draft=qa_inputs, source_notes=notes[:40],
                model=os.getenv("RG_SEO_REVIEWER_MODEL", "").strip(),
            )

    revision_report = None
    if notes:
        if reviewer_report.get("review_status") == "NEEDS_REVISION":
            from .seo_editorial_reviewer import revise_seo_candidate
            revision_report = revise_seo_candidate(
                draft=qa_inputs, source_notes=notes[:40],
                first_review=reviewer_report,
                model=os.getenv("RG_SEO_REVIEWER_MODEL", "").strip(),
            )

    # Fail closed: preserving a legacy Russian title, or model-produced
    # Russian metadata, must never be marked as safe for publishing.
    language_issues = []
    if _seo_ukrainian_language_issue(title):
        language_issues.append("назва")
    if _seo_ukrainian_language_issue(description):
        language_issues.append("опис")
    if any(_seo_ukrainian_language_issue(item) for item in variants):
        language_issues.append("A/B назви")
    if any(_seo_ukrainian_language_issue(item) for item in tags):
        language_issues.append("теги")

    return {
        "title": title,
        "title_variants": variants[:3],
        "description": description,
        "tags": tags[:15],
        "chapters": chapters,
        # Report the provider actually used. The legacy function name stays
        # for compatibility, but an LM Studio draft must never say Ollama.
        "provider": (
            f"ollama:{model}"
            if os.getenv("RG_LOCAL_AI_PROVIDER", "lmstudio").strip().lower() == "ollama"
            else "lmstudio:" + (
                os.getenv("RG_LMSTUDIO_MODEL", "").strip() or "auto"
            )
        ),

        "title_fallback_used": title_fallback_used,
        "title_unchanged": unchanged_title,
        "ab_source_quote_fallback_used": source_quote_fallback,
        "description_fallback_used": bool(payload.get("_deterministic_editor")),
        "description_model_quality_issue": str(payload.get("_description_quality_issue") or ""),
        # All AI-proposed SEO is draft-only until someone checks full SRT
        # evidence and explicitly approves each video.
        "needs_review": True,
        "editorial_approved": False,
        "publication_allowed": False,
        "source_alignment_status": (
            "BLOCKED_TOPIC_MISMATCH" if (source_alignment_conflicts or generated_conflicts) else
            "SOURCE_EVIDENCE_REVIEW" if (
                evidence_report and transcript.strip()
            ) else "TITLE_OR_SRT_UNVERIFIED" if (
                not str(current_title or "").strip() or not transcript.strip()
            ) else "SUBJECT_ROOTS_PRESENT_REVIEW"
        ),
        "timeline_blocks": (
            int(evidence_report.get("blocks_total") or 0) if evidence_report else 0
        ),
        "timeline_omitted_topics": omitted_topics,
        "ab_quality_issues": title_issues,
        "seo_language_issues": language_issues,
        "seo_editorial_quality_flags": editorial_quality_flags,
        "seo_independent_review": reviewer_report,
        "seo_revision_candidate": revision_report,
        "seo_ab_specific_diagnostic": payload.get("_ab_specific_diagnostic"),
        "seo_quote_ab_diagnostic": payload.get("_quote_ab_diagnostic"),
        "seo_editorial_gate_pass": bool(editorial_gate["editorial_gate_pass"]),
        "seo_editorial_gate_issues": editorial_gate["issues"],
        "seo_format_pass": bool(format_gate["format_pass"]),
        "seo_format_problems": format_gate["problems"],
        "seo_editorial_review_required": True,
        "review_reason": "Обов'язкова редакторська перевірка SEO. " + "; ".join(
            message for condition, message in (
                (title_fallback_used, "Модель не створила нову назву"),
                (unchanged_title and not title_fallback_used, "Основна назва не покращена"),
                (len(variants) < 3, "Недостатньо підтверджених A/B назв"),
                (source_quote_fallback, "A/B створено з дослівних цитат: перевірити редакційний стиль"),
                (not transcript.strip(), "Транскрипт відсутній; потрібна перевірка фактів"),
                (bool(evidence_report), "Аналіз усіх фрагментів: перевірити зміст перед публікацією"),
                (bool(omitted_topics), f"Деякі теми не вмістилися в опис: {len(omitted_topics)}"),
                (bool(title_issues), "; ".join(title_issues)),
                (bool(editorial_quality_flags), "Надто шаблонний SEO-текст або заголовок: перевірити вручну"),
                (bool(language_issues), "Неукраїнська мова SEO-полів: " + ", ".join(language_issues)),
                (bool(payload.get("evidence_editorial_review")), "Частину цитованих тем не вдалося надійно класифікувати"),
                (bool(payload.get("_description_quality_issue")), "Опис потребує редакторського доопрацювання"),
                (bool(payload.get("_tags_review_required")), "Менше 8 підтверджених тегів; не додавати вигадані"),
                (bool(payload.get("_fallback_review_only")), "Модель не завершила SEO; збережено лише непублікаційний чернетковий пакет"),
                (bool(payload.get("_source_topic_fallback_review_only")), "A/B із перевірених цитат: обов'язкове редакторське затвердження"),
                (bool(payload.get("_source_lexical_review_only")), "A/B сформовано лише з дослівних тем: перевірити редакційні формулювання"),
            )
            if condition
        ),
        "youtube_data_api_quota": 0,
    }


def _comment_reply_safe_novelty_ok(comment: str, reply: str) -> bool:
    """Reject replies that introduce risky concrete topics absent from the comment.

    Do not require lexical overlap because most source comments are Russian while
    local drafts are intentionally Ukrainian.
    """
    source = str(comment or "").casefold()
    target = str(reply or "").casefold()

    risky_groups = (
        ("weapon", ("збро", "оруж", "рушниц", "винтов", "пістолет", "пистолет", "гранат", "патрон", "боєприпас", "боеприпас")),
        ("war", ("війн", "войн", "фронт", "зсу", "всу", "сво", "обстріл", "обстрел", "ракета", "дрон")),
        ("health", ("лікар", "врач", "хвор", "болез", "здоров", "діагноз", "диагноз")),
        ("crime", ("злочин", "преступ", "вбив", "убий", "краді", "воров", "шахрай", "мошен")),
        ("money", ("донат", "донат", "грош", "деньг", "оплат", "переказ", "перевод", "реквізит", "реквизит")),
    )
    for _name, needles in risky_groups:
        source_has = any(item in source for item in needles)
        target_has = any(item in target for item in needles)
        if target_has and not source_has:
            return False

    # New numeric claims are especially risky in short comment replies.
    source_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?\b", source))
    target_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?\b", target))
    if target_numbers - source_numbers:
        return False

    return True


def _comment_reply_precheck_reason(comment: str) -> str:
    source = " ".join(str(comment or "").split()).strip()
    folded = source.casefold()
    words = re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґЁё0-9]+", source)

    if not source:
        return "empty_comment"

    insult_markers = (
        "туп", "дебил", "дебіл", "идиот", "ідіот", "дурак", "дурень",
        "мраз", "сволоч", "урод", "кретин", "гнид", "чмо", "орк ",
        "рашист", "нацист", "пидор", "підор",
    )
    if any(marker in folded for marker in insult_markers):
        return "insult_or_abuse"

    # Obvious low-information reactions should not receive a generated answer.
    reaction_markers = (
        "мдаа", "мда ", "лол", "ахаха", "хаха", "😂", "🤣", "😁", "😆",
        "👍", "👏", "🔥",
    )
    if len(words) <= 5 and any(marker in folded for marker in reaction_markers):
        return "low_information_reaction"

    if len(words) < 3:
        return "too_fragmentary"

    # A question word only counts as a question when it starts the sentence
    # (or follows sentence punctuation). This avoids treating phrases like
    # "скажу де правда" as an actual question.
    question_start = re.compile(
        r"(?:^|[.!?]\s+)"
        r"(?:чому|почему|навіщо|зачем|коли|когда|де|где|хто|кто|"
        r"що|что|як|как|скільки|сколько|можна|можно|чи|правда\s+ли)\b",
        re.I,
    )
    has_question = "?" in source or bool(question_start.search(folded))
    if not has_question:
        return "non_question_review"

    return ""


def generate_comment_reply_candidate_local(
    *,
    comment_text: str,
    video_title: str = "",
    video_context: str = "",
    model: str = DEFAULT_OLLAMA_MODEL,
) -> dict[str, str]:
    source = " ".join(str(comment_text or "").split()).strip()
    if not source:
        return {"state": "skipped", "reply": "", "reason": "empty_comment"}

    precheck = _comment_reply_precheck_reason(source)
    if precheck:
        return {"state": "skipped", "reply": "", "reason": precheck}

    prompt = f"""
Підготуй ОДНУ коротку чернетку відповіді на ОПУБЛІКОВАНИЙ YouTube-коментар
від імені каналу «РАША ГУДБАЙ».

Головне правило: НЕ ДОДУМУЙ зміст коментаря. Якщо він справді незрозумілий,
містить лише емодзі/випадковий уривок або для коректної відповіді потрібні
факти, яких немає в коментарі чи контексті - обери SKIP.
Відповідай лише тоді, коли коментар містить зрозуміле конкретне питання
або змістовну репліку, на яку можна відповісти без домислів. Короткі реакції,
лозунги, образи, провокації, цитати та афористичні фрази повинні бути SKIP.

Поверни ТІЛЬКИ JSON:
{{"action":"reply","reply":"...","reason":"relevant"}}
або
{{"action":"skip","reply":"","reason":"коротка причина"}}

Правила для reply:
- 1-2 короткі речення;
- відповідай лише на те, що прямо є в коментарі;
- не вигадуй факти, події, мотиви, людей, предмети, цитати чи обставини;
- не додавай зброю, війну, політику, здоров'я, моральні оцінки чи інші теми,
  якщо їх прямо немає в коментарі;
- не приписуй автору емоції чи наміри;
- не сперечайся від імені каналу і не повчай;
- не пиши канцелярські фрази на кшталт «ми прагнемо», «давайте зберігати повагу»,
  «кожен має право», якщо це не відповідає конкретному тексту;
- якщо це подяка - коротко подякуй;
- якщо це питання і відповіді немає у наданому контексті - SKIP;
- мова відповіді: українська, якщо коментар не просить інше;
- це лише чернетка, вона не буде автоматично опублікована.

ВІДЕО:
{video_title}

КОНТЕКСТ:
{video_context[:3000]}

КОМЕНТАР:
{source}
""".strip()

    try:
        raw = ollama_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Ти обережний редактор коментарів. Краще SKIP, ніж "
                        "нерелевантна або вигадана відповідь."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            model=model,
            temperature=0.05,
            json_mode=True,
        )
        payload = _extract_json_object(raw)
    except Exception as exc:
        return {
            "state": "error",
            "reply": "",
            "reason": f"ollama_error:{str(exc)[:160]}",
        }

    action = str(payload.get("action") or "").strip().casefold()
    reason = str(payload.get("reason") or "").strip()[:240]
    reply = " ".join(str(payload.get("reply") or "").split()).strip()
    reply = reply.replace("—", "-").replace("–", "-")

    if action != "reply" or not reply:
        return {
            "state": "skipped",
            "reply": "",
            "reason": reason or "model_skip",
        }
    if len(reply) > 420:
        return {"state": "skipped", "reply": "", "reason": "reply_too_long"}
    if not _comment_reply_safe_novelty_ok(source, reply):
        return {
            "state": "skipped",
            "reply": "",
            "reason": "unsafe_new_topic_or_number",
        }

    banned = (
        "відео створене з любов",
        "підготував, як просили",
        "підготували, як просили",
        "ми прагнемо",
        "давайте зберігати повагу",
        "кожен має право",
        "не збираємося вступати",
        "не звертаємо уваги",
    )
    folded = reply.casefold()
    if any(item in folded for item in banned):
        return {
            "state": "skipped",
            "reply": "",
            "reason": "generic_or_hallucinated_phrase",
        }

    return {"state": "ready", "reply": reply, "reason": reason or "relevant"}


def generate_comment_reply_local(
    *,
    comment_text: str,
    video_title: str = "",
    video_context: str = "",
    model: str = DEFAULT_OLLAMA_MODEL,
) -> str:
    candidate = generate_comment_reply_candidate_local(
        comment_text=comment_text,
        video_title=video_title,
        video_context=video_context,
        model=model,
    )
    return str(candidate.get("reply") or "") if candidate.get("state") == "ready" else ""

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
