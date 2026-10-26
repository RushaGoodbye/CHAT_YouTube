"""RG SEO Engine 1.0: independent, offline, source-bound SEO draft generator.

No YouTube writes; no UI or application database dependencies.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class SeoDraft:
    video_id: str
    title: str
    ab_titles: tuple[str, str, str]
    description: str
    tags: tuple[str, ...]
    chapters: str
    needs_review: bool = True


def _words(value: str) -> set[str]:
    return set(re.findall(r"[a-zа-яёіїєґ0-9]{4,}", value.casefold()))


def generate_draft(
    *, video_id: str, current_title: str, transcript: str,
    generate_json: Callable[[str], str],
) -> SeoDraft:
    """Accept only a real exact-ID transcript and a schema-valid model response.

    The model callback can use local Ollama structured output. Drafts are
    ALWAYS review-only, and never change YouTube metadata.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Invalid YouTube Video ID")
    source = " ".join(transcript.split())
    if len(source) < 150:
        raise ValueError("Transcript missing or too short")
    prompt = (
        "Ти редактор каналу РАША ГУДБАЙ. Згенеруй лише JSON: "
        "title, ab_titles (рівно 3), description, tags (8–15 релевантних), chapters. "
        "Назви російською, опис українською. "
        "Не вигадуй факти, цитати чи законодавчі зміни. "
        "Бери теми лише з розшифровки, уникай шаблонних фраз. "
        "Усі твердження залишаються чернеткою до редакторського схвалення. "
        "ВІДЕО ID: " + video_id + "\nПОТОЧНА НАЗВА: " +
        current_title + "\nРОЗШИФРОВКА:\n" + source[:24000]
    )
    raw = generate_json(prompt)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("SEO response must be an object")
    title = str(data.get("title") or "").strip()
    variants = data.get("ab_titles")
    description = str(data.get("description") or "").strip()
    tags = data.get("tags")
    chapters = str(data.get("chapters") or "").strip()
    if not title or len(title) > 100:
        raise ValueError("Invalid primary title")
    if not isinstance(variants, list) or len(variants) != 3 or any(
        not isinstance(v, str) or not v.strip() or len(v) > 100 for v in variants
    ):
        raise ValueError("Exactly three valid A/B titles required")
    if len({title.casefold(), *(v.strip().casefold() for v in variants)}) < 4:
        raise ValueError("A/B titles are duplicates")
    if not 260 <= len(description) <= 4500:
        raise ValueError("Description length invalid")
    if not isinstance(tags, list) or not 8 <= len(tags) <= 15 or any(
        not isinstance(t, str) or not t.strip() for t in tags
    ):
        raise ValueError("Tags invalid")
    if len({str(t).strip().casefold() for t in tags}) < 8:
        raise ValueError("At least eight unique tags required")
    # YouTube's tag budget counts commas between tags as well as values.
    if len(",".join(tags)) > 500:
        raise ValueError("Tag text exceeds YouTube limit")
    # A timestamped chapter list must not invent negative or impossible times.
    if chapters:
        for line in chapters.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.match(r"^(\d{1,2}:\d{2}(?::\d{2})?)\s+\S", line)
            if not match:
                raise ValueError("Invalid chapters format")
            parts = [int(p) for p in match.group(1).split(":")]
            if parts[-1] >= 60 or (len(parts) == 3 and parts[-2] >= 60):
                raise ValueError("Invalid chapter timestamp")
    # Reject obvious transcript/title swaps: central nouns in the original
    # title must occur in the transcript, not merely in generated prose.
    stop = {"раша", "гудбай", "россии", "россия", "чат", "рулетка", "можно"}
    anchors = (_words(current_title) - stop)
    if anchors and len(anchors & _words(source)) == 0:
        raise ValueError("SOURCE_VIDEO_MISMATCH: title topic absent from transcript")
    school_topic = (
        any(w in current_title.casefold() for w in ("школ", "учител", "преподав"))
        and any(w in current_title.casefold() for w in
                ("осужден", "судим", "преступлен", "тяжк"))
    )
    if school_topic:
        def _has_topic(value: str) -> bool:
            v = value.casefold()
            return (any(w in v for w in
                        ("школ", "учител", "преподав", "педагог"))
                    and any(w in v for w in
                            ("осужден", "судим", "преступлен", "тяжк",
                             "судим", "уголовн", "засуджен")))
        if not _has_topic(source):
            raise ValueError("SOURCE_VIDEO_MISMATCH: school crime theme missing")
        if not _has_topic(title + " " + description):
            raise ValueError("SEO_TOPIC_MISMATCH: generated text abandons subject")
    return SeoDraft(
        video_id=video_id, title=title,
        ab_titles=tuple(v.strip() for v in variants),
        description=description, tags=tuple(t.strip() for t in tags),
        chapters=chapters,
    )
