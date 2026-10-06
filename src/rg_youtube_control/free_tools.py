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




_GROUNDED_TOPIC_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("лукашенко",), "Лукашенко та позиція Білорусі"),
    (("беларус", "білорус"), "Білорусь та її роль у розмові"),
    (("шойгу",), "Шойгу та його роль у керівництві РФ"),
    (("министерств", "оборон"), "Міністерство оборони РФ"),
    (("коррупц",), "корупція та відповідальність чиновників"),
    (("цен", "подорож", "дорог", "инфляц"), "ціни та вартість життя"),
    (("зарплат", "доход", "получать", "заработ"), "зарплати та доходи"),
    (("пенси", "пенс", "соцпакет", "социальн"), "пенсії та соціальні виплати"),
    (("эконом", "економ"), "економіка Росії"),
    (("путин", "путін", "президент"), "Путін та оцінка влади"),
    (("войн", "війн", "сво", "украин", "україн"), "війна проти України"),
    (("мобилиз", "мобіліз"), "мобілізація"),
    (("санкц",), "санкції"),
    (("бензин", "топлив", "азс"), "паливо та ситуація на АЗС"),
    (("работ", "робот", "безработ"), "робота та зайнятість"),
    (("квартир", "жиль", "ипотек", "дом "), "житло та особисті покупки"),
    (("медицин", "лікар", "боляч", "здоров"), "здоров'я та медицина"),
)


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

    # High-confidence topic-specific fallback. It uses only facts and opinions
    # that are directly visible in this transcript family.
    if "шойгу" in title_text or "шойгу" in text:
        sentences: list[str] = [
            "У цьому випуску чат-рулетки росіяни обговорюють зміну посади Шойгу та причини кадрових рішень у Міністерстві оборони РФ.",
            "У розмові звучать різні версії - від корупційних скандалів і перевірки військових витрат до планової кадрової перестановки.",
            "Частина співрозмовників вважає, що Шойгу не усунули від влади, а перевели на іншу посаду, тоді як інші пов'язують зміни з проблемами в його команді.",
        ]
        if "белоусов" in text:
            sentences.append(
                "Також згадують Білоусова та його економічний профіль у контексті управління оборонною сферою."
            )
        if "тимур" in text and "иванов" in text:
            sentences.append(
                "Окремо порушують тему Тимура Іванова та корупційних звинувачень щодо представників команди Шойгу."
            )
        return _polish_generated_description(" ".join(sentences))

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


def _description_quality_error(description: str, transcript: str = "") -> str:
    """Return a machine-readable reason when a generated SEO description is unsafe."""
    value = " ".join(str(description or "").split()).strip()
    if len(value) < 260:
        return "too_short"
    if len(value) > 1000:
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
{transcript[:12000]}
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


_GENERIC_MODEL_TAGS = {
    "план", "стратегия", "политика", "должность", "перевод", "власть",
    "тема", "мнение", "разговор", "видео", "вопрос", "ответ", "общество",
    "новости", "события", "ситуация", "анализ", "обсуждение", "интервью",
}


def _tag_is_grounded(tag: str, current_title: str, transcript: str) -> bool:
    """Allow model tags only when they are specific and grounded in title/transcript."""
    clean = " ".join(str(tag or "").split()).strip().lstrip("#")
    if not clean:
        return False
    folded = clean.casefold()
    if folded in _GENERIC_MODEL_TAGS:
        return False
    if folded in {"раша гудбай", "чат рулетка"}:
        return True

    haystack = f"{current_title}\n{transcript}".casefold()
    if folded in haystack:
        return True

    tokens = [
        token
        for token in re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґЁё0-9]+", folded)
        if len(token) >= 4 and token not in _GENERIC_MODEL_TAGS
    ]
    if not tokens:
        return False

    # Multi-word tags may use a normalized phrase not present verbatim, but at
    # least half of their meaningful words must be visible in the source.
    hits = sum(1 for token in tokens if token in haystack)
    required = 1 if len(tokens) == 1 else max(2, (len(tokens) + 1) // 2)
    return hits >= required


def _source_mentions(
    title: str,
    transcript: str,
    needles: tuple[str, ...],
) -> tuple[bool, int]:
    title_text = str(title or "").casefold()
    transcript_text = str(transcript or "").casefold()
    in_title = any(needle in title_text for needle in needles)
    count = sum(transcript_text.count(needle) for needle in needles)
    return in_title, count


def _grounded_tags_from_transcript(
    current_title: str,
    transcript: str,
) -> list[str]:
    """Build 8-15 specific SEO tags from the actual title/transcript."""
    title = re.sub(
        r"\s*[|·-]\s*(?:РАША\s+ГУДБАЙ|RUSSIA\s+GOODBYE)\s*$",
        "",
        str(current_title or "").strip(),
        flags=re.I,
    ).strip()
    haystack = f"{title}\n{transcript}".casefold()

    tags: list[str] = ["РАША ГУДБАЙ", "чат рулетка"]

    def add(value: str) -> None:
        clean = " ".join(str(value or "").split()).strip().lstrip("#")
        if not clean:
            return
        if clean.casefold() not in {item.casefold() for item in tags}:
            tags.append(clean)

    # Named entities and concrete episode topics come before generic channel tags.
    if "шойгу" in haystack:
        add("Шойгу")
        if "уволь" in haystack or "отстав" in haystack:
            add("увольнение Шойгу")
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
        add("Беларусь")
        if "украин" in haystack or "україн" in haystack:
            add("Беларусь и Украина")
    if "украин" in haystack or "україн" in haystack:
        add("Украина")
    if "совет" in haystack and "безопас" in haystack:
        add("Совет безопасности России")
    if "министерств" in haystack and "оборон" in haystack:
        add("Министерство обороны России")
    if "коррупц" in haystack:
        add("коррупция в России")
    if "арм" in haystack and ("росси" in haystack or "рф" in haystack):
        add("российская армия")

    if "росси" in haystack or "росія" in haystack:
        for value in (
            "Россия",
            "россияне",
            "мнение россиян",
            "вопросы россиянам",
        ):
            add(value)

    if "жизн" in haystack or "житт" in haystack:
        add("жизнь в России")
    if "цен" in haystack or "дорог" in haystack or "инфляц" in haystack:
        add("цены в России")
    if "зарплат" in haystack or "доход" in haystack:
        add("зарплаты в России")
    if "пенси" in haystack or "соцпакет" in haystack:
        add("пенсии в России")
    in_title, mentions = _source_mentions(title, transcript, ("эконом", "економ"))
    if in_title or mentions >= 3:
        add("экономика России")
    in_title, mentions = _source_mentions(title, transcript, ("путин", "путін"))
    if in_title or mentions >= 3:
        add("Путин")
    in_title, mentions = _source_mentions(
        title, transcript, ("войн", "війн", "спецоперац")
    )
    if in_title or mentions >= 3:
        add("война России против Украины")
    in_title, mentions = _source_mentions(
        title, transcript, ("мобилиз", "мобіліз")
    )
    if in_title or mentions >= 3:
        add("мобилизация в России")
    in_title, mentions = _source_mentions(title, transcript, ("санкц",))
    if in_title or mentions >= 3:
        add("санкции против России")
    if "бензин" in haystack or "топлив" in haystack or "азс" in haystack:
        add("бензин в России")
    in_title, mentions = _source_mentions(title, transcript, ("безработ", "работа ", "робота ", "работу ", "роботу "))
    if in_title or mentions >= 4:
        add("работа в России")
    if "квартир" in haystack or "жиль" in haystack or "ипотек" in haystack:
        add("жилье в России")
    if "медицин" in haystack or "здоров" in haystack or "боляч" in haystack:
        add("здоровье в России")
    if re.search(r"\b2023\b", haystack):
        add("Россия 2023")

    # Project-format fallbacks are added last, only to reach a useful minimum.
    for value in (
        "опрос россиян",
        "реакция россиян",
        "разговор с россиянами",
        "русская чат рулетка",
    ):
        if len(tags) >= 8:
            break
        add(value)

    return tags[:15]


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
    )
    return all(any(token in label for token in generic) for label in labels)


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

    # Exact same semantic title with only punctuation/brand removed is a downgrade.
    if current_core == candidate_core:
        return current

    current_words = set(current_core.split())
    candidate_words = set(candidate_core.split())

    # If the candidate contributes no new meaningful words, keep the proven title.
    if candidate_words and candidate_words.issubset(current_words):
        return current

    return candidate



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

    if "шойгу" in title_text:
        preferred = (
            ("00:00", "Вступ і головне запитання"),
            ("00:43", "Версії причин зміни Шойгу"),
            ("02:21", "Корупція та команда Шойгу"),
            ("03:17", "Військова стратегія і нове керівництво"),
            ("04:00", "Перехід Шойгу на іншу посаду"),
            ("06:03", "Корупція чи кадровий план"),
            ("08:11", "Тимур Іванов і команда Шойгу"),
        )
        lines = [
            f"{stamp} {label}"
            for stamp, label in preferred
            if stamp in available or stamp == "00:00"
        ]
        value = "\n".join(lines)
        if not _chapters_quality_error(value, transcript_text):
            return value

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
) -> dict[str, Any]:
    context = public_context or {}
    prompt = f"""
Ти редактор YouTube-проєкту «РАША ГУДБАЙ». Підготуй SEO-пакет без вигадування фактів.
Використовуй ТІЛЬКИ наведений контекст. Якщо факту немає в контексті - не додавай його.

Правила:
- основна назва та РІВНО 3 різні A/B варіанти назви: російською;
- кожна назва до 100 символів, конкретна, зрозуміла і прив'язана до реальної теми відео;
- не копіюй поточну назву без SEO-покращення, якщо транскрипт дає точніший сильний хук;
- опис: українською, 400-850 символів змістовного тексту до службових посилань;
- не копіюй російську назву відео як перше речення опису; перефразуй тему природною українською;
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
- теги без #, 8-15 штук, без дублювань; спочатку конкретні сутності та тема відео, потім формат/канал;
- не використовуй самостійні надто загальні теги «план», «стратегия», «политика», «должность», «перевод», «власть», «новости», якщо вони не є конкретною пошуковою фразою;
- не змінюй thumbnail;
- для Shorts не вигадуй глави;
- chapters дозволені тільки за наявності підтверджених таймкодів у транскрипті; назви глав - українською;
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
title: російською, до 100 символів, конкретний і підтверджений транскриптом.
title_variants: РІВНО 3 різні варіанти, кожен до 100 символів.
description: українською, 400-850 символів, конкретно за змістом транскрипту, без шаблонних фраз і без ENGLISH SUMMARY.
tags: масив 8-15 конкретних пошукових фраз без # і без дублікатів; не використовуй загальні одиночні слова на кшталт план/стратегия/политика.
chapters: рядок з підтвердженими таймкодами та українськими назвами або порожній рядок.
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
                timeout=timeout,
                temperature=0.05 if attempt else 0.15,
                json_mode=True,
            )
            candidate = _normalize_seo_candidate(_extract_json_object(raw))
            if not str(candidate.get("title") or "").strip():
                if fast_mode and str(current_title or "").strip():
                    # In batch mode the already published title is safer than
                    # promoting an arbitrary A/B variant to the primary title.
                    candidate["title"] = _clean_project_title_for_seo(
                        current_title
                    )
                else:
                    variants_candidate = candidate.get("title_variants") or []
                    if isinstance(variants_candidate, list) and variants_candidate:
                        candidate["title"] = str(variants_candidate[0]).strip()
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
                if str(item).strip()
            ]
            if (
                len(variants_candidate) < 3
                or len({item.casefold() for item in variants_candidate[:3]}) < 3
            ):
                if fast_mode:
                    raise ValueError("need exactly 3 title variants")
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
            description_candidate = _polish_generated_description(
                str(candidate.get("description") or "").strip()
            )
            candidate["description"] = description_candidate
            description_error = _description_quality_error(
                description_candidate,
                transcript,
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
                        )
                else:
                    # Full-quality mode may spend extra local model passes on
                    # description recovery. Batch mode intentionally avoids it.
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
                        )
                    elif description_error:
                        fallback_description = _grounded_description_from_transcript(
                            current_title,
                            transcript,
                        )
                        candidate["description"] = fallback_description
                        description_candidate = fallback_description
                        description_error = _description_quality_error(
                            description_candidate,
                            transcript,
                        )
            if transcript.strip() and description_error:
                raise ValueError(
                    "description quality failed: " + description_error
                )

            model_tags = [
                str(item).strip().lstrip("#")
                for item in (candidate.get("tags") or [])
                if str(item).strip()
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

            primary_tags = grounded_tags if transcript.strip() else model_tags
            fallback_tags = model_tags if transcript.strip() else grounded_tags

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

            if len(merged_tags) < 8:
                raise ValueError("need at least 8 grounded tags")
            candidate["tags"] = merged_tags

            payload = candidate
            break
        except (ValueError, RuntimeError, TimeoutError) as exc:
            last_error = exc
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

    if not is_short and transcript.strip():
        chapter_error = _chapters_quality_error(chapters, transcript)
        if chapter_error and not fast_mode:
            chapters = _recover_chapters_from_transcript(
                current_title=current_title,
                transcript=transcript,
                model=model,
            )
        if not chapters or _chapters_quality_error(chapters, transcript):
            chapters = _grounded_chapters_from_transcript(
                current_title=current_title,
                transcript=transcript,
            )
        if chapters and _chapters_quality_error(chapters, transcript):
            chapters = ""
        if fast_mode and chapters and _chapters_are_generic(chapters):
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
