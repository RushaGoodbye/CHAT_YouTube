"""Transcript-wide, evidence-anchored local SEO analysis (zero YouTube API).

Every timestamped caption belongs to exactly one analysis block. Blocks are
timeline windows, NOT claimed speaker/dialogue boundaries. The language model
can propose topics only with a verbatim quote found in that block. Unsupported
claims are excluded and flagged for review. The full audit stays on disk.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable

ANALYSIS_SCHEMA = "RG_DIALOGUE_EVIDENCE_V1"


def _compact(value: object) -> str:
    return " ".join(str(value or "").split())


def _stamp(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{(total // 60) % 60:02d}:{total % 60:02d}"


def split_timeline(
    rows: Iterable[dict[str, Any]],
    *,
    max_chars: int = 5000,
    max_span_seconds: int = 300,
) -> list[dict[str, Any]]:
    """Cover ALL caption rows; split overlong captions without skipping text."""
    if max_chars < 250:
        raise ValueError("max_chars має бути щонайменше 250")
    if max_span_seconds < 10:
        raise ValueError("max_span_seconds має бути щонайменше 10")
    blocks: list[dict[str, Any]] = []
    lines: list[str] = []
    used = 0
    first_time = 0.0
    last_time = 0.0
    current_cues = 0

    def flush() -> None:
        nonlocal lines, used, current_cues
        if lines:
            blocks.append({
                "index": len(blocks) + 1,
                "start": first_time,
                "end": last_time,
                "start_stamp": _stamp(first_time),
                "end_stamp": _stamp(last_time),
                "text": "\n".join(lines),
                "pieces": current_cues,
            })
        lines = []
        used = 0
        current_cues = 0

    for row in rows:
        value = _compact(row.get("text"))
        if not value:
            continue
        try:
            start = max(0.0, float(row.get("start") or 0))
        except (ValueError, TypeError):
            start = last_time
        try:
            duration = max(0.0, float(row.get("duration") or 0))
        except (ValueError, TypeError):
            duration = 0
        # Split an unusually long single caption on word boundaries instead
        # of silently truncating it.
        words = value.split()
        pieces: list[str] = []
        piece = ""
        for word in words:
            while len(word) > max_chars:
                if piece:
                    pieces.append(piece)
                    piece = ""
                pieces.append(word[:max_chars])
                word = word[max_chars:]
            candidate = f"{piece} {word}".strip()
            if len(candidate) > max_chars and piece:
                pieces.append(piece)
                piece = word
            else:
                piece = candidate
        if piece:
            pieces.append(piece)

        for part in pieces:
            # Use time for grouping but do not claim each group is a dialogue.
            if lines and (
                used + len(part) + 1 > max_chars
                or start - first_time >= max_span_seconds
            ):
                flush()
            if not lines:
                first_time = start
            last_time = max(last_time, start + duration)
            lines.append(part)
            used += len(part) + 1
            current_cues += 1
    flush()
    return blocks


def _cache_file(cache_dir: Path, block: dict[str, Any], model: str) -> Path:
    fingerprint = hashlib.sha256(
        f"{ANALYSIS_SCHEMA}\n{model}\n{block['text']}".encode("utf-8")
    ).hexdigest()
    return cache_dir / f"{fingerprint}.json"


def _validate_topics(candidate: Any, block: dict[str, Any]) -> dict[str, Any]:
    source = _compact(block["text"]).casefold()
    # ASR/LLM may adjust commas or quote marks, but not source words.
    source_words = " " + re.sub(r"[^\w]+", " ", source, flags=re.UNICODE).strip() + " "
    topics: list[dict[str, str]] = []
    if isinstance(candidate, dict):
        proposed = candidate.get("topics") or []
    else:
        proposed = []
    for item in proposed if isinstance(proposed, list) else []:
        if not isinstance(item, dict):
            continue
        evidence = _compact(item.get("evidence"))
        topic = _compact(item.get("topic"))
        summary = _compact(item.get("summary_uk"))
        # EXACT text-grounding: the quote has to appear in this same block.
        if (
            not (8 <= len(evidence) <= 240)
            or (
                " " + re.sub(
                    r"[^\w]+", " ", evidence.casefold(), flags=re.UNICODE
                ).strip() + " "
            ) not in source_words
            or not (5 <= len(topic) <= 110)
            or not (15 <= len(summary) <= 350)
        ):
            continue
        topics.append({
            "topic": topic,
            "summary_uk": summary,
            "evidence": evidence,
        })
        if len(topics) >= 3:
            break

    if not topics:
        # A non-model fallback is an excerpt, NOT an inferred topic.
        excerpt = _compact(block["text"])[:200]
        return {"topics": [], "excerpt": excerpt, "verified": False}
    return {"topics": topics, "excerpt": "", "verified": True}


def analyze_all_timeline_blocks(
    rows: Iterable[dict[str, Any]],
    *,
    model: str,
    chat: Callable[..., str],
    cache_dir: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
    max_chars: int = 5000,
    max_span_seconds: int = 300,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """Analyze every caption block, with bounded input and resumable cache."""
    blocks = split_timeline(
        rows, max_chars=max_chars, max_span_seconds=max_span_seconds
    )
    if not blocks:
        raise ValueError("Немає субтитрів для аналізу всіх діалогів.")
    cache = Path(cache_dir) if cache_dir is not None else None
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    failed: list[int] = []
    cache_hits = 0

    for index, block in enumerate(blocks, 1):
        if progress is not None:
            progress(f"Аналіз фрагментів: {index}/{len(blocks)} · {_stamp(block['start'])}")
        path = _cache_file(cache, block, model) if cache is not None else None
        item: dict[str, Any] | None = None
        if path is not None and path.is_file():
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                item = _validate_topics(saved, block)
                cache_hits += 1
            except (ValueError, OSError, TypeError):
                item = None

        if item is None:
            prompt = (
                "Ти аналізуєш ОДИН хронологічний фрагмент транскрипту "
                "відео з чат-рулетки. Не вигадуй фактів, імен або цитат. "
                "Відокремлюй позиції співрозмовників від доведених фактів. "
                "Поверни тільки JSON: "
                '{"topics":[{"topic":"коротка тема українською",'
                '"summary_uk":"що саме сказали співрозмовники, українською",'
                '"evidence":"дослівний уривок 8-240 символів із фрагмента"}]}. '
                "Для кожної з 1-3 тем обов'язкова точна цитата з тексту. "
                "Якщо фрагмент шумний або без змісту, topics=[]. "
                "Не включай до цитат номер часу.\n\n"
                f"ФРАГМЕНТ {index}/{len(blocks)}:\n{block['text']}"
            )
            try:
                raw = chat(
                    [
                        {"role": "system", "content": "Поверни тільки JSON з перевірюваними доказами."},
                        {"role": "user", "content": prompt},
                    ],
                    model=model,
                    timeout=timeout,
                    temperature=0.05,
                    json_mode=True,
                )
                candidate = json.loads(str(raw).strip())
                item = _validate_topics(candidate, block)
            except (ValueError, RuntimeError, TimeoutError, TypeError, OSError):
                item = _validate_topics({}, block)
            if path is not None and item["verified"]:
                try:
                    # Cache only already verified evidence, never partial errors.
                    tmp = path.with_suffix(".tmp")
                    tmp.write_text(
                        json.dumps({"topics": item["topics"]}, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    tmp.replace(path)
                except OSError:
                    pass

        if not item["verified"]:
            failed.append(index)
        results.append({
            "index": index,
            "start": block["start"],
            "end": block["end"],
            "start_stamp": block["start_stamp"],
            "end_stamp": block["end_stamp"],
            "topics": item["topics"],
            "excerpt": item["excerpt"],
            "verified": item["verified"],
        })

    return {
        "schema": ANALYSIS_SCHEMA,
        "blocks_total": len(blocks),
        "blocks_analyzed": len(results),
        "blocks_with_evidence": len(blocks) - len(failed),
        "unverified_blocks": failed,
        "cache_hits": cache_hits,
        "rows_covered": sum(b["pieces"] for b in blocks),
        "blocks": results,
        # "100% of blocks processed" does not mean 100% of claims verified.
        "needs_review": bool(failed),
    }


def evidence_outline_text(report: dict[str, Any]) -> str:
    """Compact all verified block notes for final model, without omission."""
    lines: list[str] = []
    for block in report.get("blocks") or []:
        stamp = str(block.get("start_stamp") or "")
        topics = block.get("topics") or []
        if topics:
            for item in topics:
                lines.append(
                    f"[{stamp}] ТЕМА: {item['topic']} | "
                    f"ТЕЗА: {item['summary_uk']} | "
                    f"ЦИТАТА: {item['evidence']}"
                )
        else:
            lines.append(
                f"[{stamp}] НЕПЕРЕВІРЕНИЙ ФРАГМЕНТ: "
                f"{str(block.get('excerpt') or '')[:150]}"
            )
    return "\n".join(lines)


def preserve_outline_topics(
    description: str,
    report: dict[str, Any],
    *,
    max_body_bytes: int = 3900,
) -> tuple[str, list[str]]:
    """Add missing grounded topics without silently discarding the outline.

    Return omitted topics for manual review if even the topic list cannot fit.
    Service links and three hashtags are appended later by safe_description_fix.
    """
    source = str(description or "").strip()
    unique: list[str] = []
    seen: set[str] = set()
    for block in report.get("blocks") or []:
        for item in block.get("topics") or []:
            topic = _compact(item.get("topic"))
            if topic and topic.casefold() not in seen:
                seen.add(topic.casefold())
                unique.append(topic)

    if not unique:
        return source, []
    missing = [topic for topic in unique if topic.casefold() not in source.casefold()]
    if not missing:
        return source, []

    # Preserve the core synopsis and every distinct grounded subject where
    # possible. Do not byte-truncate Cyrillic or silently remove topics.
    base = source
    footer = "\n\nІнші підтверджені теми розмов:\n"
    excluded: list[str] = []
    included: list[str] = []
    for topic in missing:
        candidate = base + footer + "\n".join(
            f"• {item}" for item in (included + [topic])
        )
        if len(candidate.encode("utf-8")) <= max_body_bytes:
            included.append(topic)
        else:
            excluded.append(topic)
    if included:
        base += footer + "\n".join(f"• {item}" for item in included)
    return base, excluded



def ab_title_issues(
    variants: Iterable[str],
    report: dict[str, Any] | None = None,
) -> list[str]:
    """Detect missing, duplicate, overly generic or unsupported A/B hooks."""
    from difflib import SequenceMatcher

    values = [_compact(value) for value in variants if _compact(value)]
    issues: list[str] = []
    if len(values) != 3:
        issues.append("Потрібно рівно 3 назви для A/B.")
        return issues
    if any(len(value) > 100 or len(value) < 20 for value in values):
        issues.append("Назви A/B мають бути змістовними (20-100 символів).")
    normal = [
        re.sub(
            r"^(?:чат\s*рулетка|раша\s*гудбай)[\s:.|!-]*",
            "", value.casefold(), flags=re.I,
        ).strip()
        for value in values
    ]
    for left in range(3):
        for right in range(left + 1, 3):
            if SequenceMatcher(None, normal[left], normal[right]).ratio() >= 0.85:
                issues.append(
                    f"Варіанти {left + 1} і {right + 1} повторюють один сюжетний гачок."
                )

    if report:
        # Conservative case-folded stem overlap. Lack of overlap is a review
        # warning, not proof that the proposed phrase is false.
        source = evidence_outline_text(report).casefold().translate(
            str.maketrans({"і": "и", "ї": "и", "є": "е", "ґ": "г"})
        )
        stems = {
            word[:5] for word in re.findall(r"[a-zа-яё0-9]{5,}", source)
            if word not in {"цитата", "тема", "теза", "співрозмовник"}
        }
        # A shared supported keyword must not conceal an invented unrelated
        # two-word subject (regression: "family psychology" in political SEO).
        unsupported_subjects = (
            r"семейн\w*\s+психолог\w*",
            r"сімейн\w*\s+психолог\w*",
            r"семейной\s+психологии",
        )
        # Only verified verbatim evidence supports a subject. A generated
        # summary/topic is not evidence, even when it repeats title words.
        evidence_text = " ".join(
            _compact(item.get("evidence")).casefold()
            for block in report.get("blocks") or []
            for item in block.get("topics") or []
            if isinstance(item, dict)
        )
        supported_family_topic = any(
            re.search(pattern, evidence_text, flags=re.UNICODE)
            for pattern in unsupported_subjects
        )
        for index, value in enumerate(values, 1):
            title_lower = value.casefold()
            if not supported_family_topic and any(
                re.search(pattern, title_lower, flags=re.UNICODE)
                for pattern in unsupported_subjects
            ):
                issues.append(
                    f"A/B варіант {index} містить непідтверджену тему сімейної психології."
                )
            words = re.findall(
                r"[a-zа-яё0-9]{5,}",
                value.casefold().translate(
                    str.maketrans({"і": "и", "ї": "и", "є": "е", "ґ": "г"})
                ),
            )
            meaningful = [
                word for word in words
                if word not in {
                    "чатрулетка", "рулетка", "рашагудбай",
                    "россияне", "россия", "российск",
                }
            ]
            if meaningful and not any(
                word[:5] in stems for word in meaningful
            ):
                issues.append(
                    f"A/B варіант {index} не має підтверджених тематичних слів."
                )
    return issues
