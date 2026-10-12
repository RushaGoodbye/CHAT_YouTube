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
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"[{stamp}] ТЕМА: {item.get('topic', '')} | "
                    f"ТЕЗА: {item.get('summary_uk', '')} | "
                    f"ЦИТАТА: {item.get('evidence', '')}"
                )
        else:
            lines.append(
                f"[{stamp}] НЕПЕРЕВІРЕНИЙ ФРАГМЕНТ: "
                f"{str(block.get('excerpt') or '')[:150]}"
            )
    return "\n".join(lines)


def _topic_display_uk(topic: str, current_title: str = "") -> str:
    """Clean source-topic labels; never copy garbled ASR proper names verbatim."""
    from difflib import SequenceMatcher

    value = _compact(topic)
    value = re.sub(r"^дискусія\s+про\s+", "", value, flags=re.I)
    value = re.sub(
        r"\b(?:увольнение|увольнения|увільнення)\b",
        "звільнення", value, flags=re.I,
    )
    value = re.sub(r"^корупцію\b", "корупція", value, flags=re.I)
    # A capitalized ASR name may be a close misspelling of an actual ALL-CAPS
    # person name in the video title (real example: Шагу vs ШОЙГУ).
    canonical = [
        word for word in re.findall(r"\b[А-ЯЁІЇЄҐ]{4,}\b", current_title)
        if word.casefold() not in {"раша", "гудбай", "чат", "рулетка"}
    ]
    for word in set(re.findall(r"\b[А-ЯЁІЇЄҐ][а-яёіїєґ]{3,}\b", value)):
        candidates = [
            name for name in canonical
            if SequenceMatcher(None, word.casefold(), name.casefold()).ratio() >= 0.65
        ]
        if len(candidates) == 1:
            normalized = candidates[0].capitalize()
            value = re.sub(r"\b" + re.escape(word) + r"\b", normalized, value)
    return value


def grounded_chapters_from_evidence(
    report: dict[str, Any],
    timed_transcript: str,
    *,
    current_title: str = "",
    min_confidence: float = 82.0,
) -> str:
    """Find genuine caption timestamps for independently quoted story points.

    Never use a fixed script, equal time slices, invented persons or chapter
    names inferred from the video title alone. If reliable alignment fails,
    return no chapters and require human review.
    """
    try:
        from rapidfuzz.fuzz import partial_ratio
    except ImportError:
        return ""

    def seconds(stamp: str) -> int:
        parts = str(stamp).split(":")
        if len(parts) not in (2, 3):
            return -1
        try:
            values = [int(part) for part in parts]
        except ValueError:
            return -1
        return (
            values[0] * 60 + values[1]
            if len(values) == 2 else
            values[0] * 3600 + values[1] * 60 + values[2]
        )

    def compact(value: str) -> str:
        return " ".join(re.findall(r"[a-zа-яёіїєґ0-9]+", value.casefold()))

    captions: list[tuple[int, str, str]] = []
    for line in str(timed_transcript or "").splitlines():
        match = re.match(r"^\[(\d{2}:\d{2}(?::\d{2})?)\]\s+(.+)", line)
        if not match:
            continue
        at = seconds(match.group(1))
        text = compact(match.group(2))
        if at >= 0 and text:
            captions.append((at, match.group(1), text))
    if len(captions) < 10:
        return ""

    verified: list[tuple[int, str, str, float]] = []
    for block in report.get("blocks") or []:
        lo = seconds(str(block.get("start_stamp") or ""))
        hi = seconds(str(block.get("end_stamp") or ""))
        for item in block.get("topics") or []:
            if not isinstance(item, dict):
                continue
            quote = compact(str(item.get("evidence") or ""))
            label = _topic_display_uk(str(item.get("topic") or ""), current_title)
            if len(quote) < 25 or len(label) < 8:
                continue
            # Caption windows can span multiple short ASR chunks.
            best_score, best_index = 0.0, -1
            for i, (at, _stamp, _text) in enumerate(captions):
                if lo >= 0 and at < lo - 12:
                    continue
                if hi >= 0 and at > hi + 12:
                    continue
                window = " ".join(part[2] for part in captions[i:i + 10])
                # A long caption window can contain the quote even when
                # its first timestamp precedes the speech by a minute.
                # Prefer rows where the *beginning* of the quote aligns.
                start_window = " ".join(part[2] for part in captions[i:i + 2])
                opening = " ".join(quote.split()[:6])
                score = (
                    0.76 * float(partial_ratio(quote, window))
                    + 0.24 * float(partial_ratio(opening, start_window))
                )
                if score > best_score:
                    best_score, best_index = score, i
            if best_index >= 0 and best_score >= min_confidence:
                at, stamp, _ = captions[best_index]
                verified.append((at, stamp, label, best_score))
    if len(verified) < 2:
        return ""

    # Prefer the highest-confidence quote within a 20-second cluster.
    selected: list[tuple[int, str, str, float]] = []
    for item in sorted(verified, key=lambda x: (-x[3], x[0])):
        if any(abs(item[0] - existing[0]) < 20 for existing in selected):
            continue
        selected.append(item)
    selected.sort(key=lambda x: x[0])
    if len(selected) < 2:
        return ""

    def concept(value: str) -> str:
        # "Причина звільнення Шойгу", "Звільнення Шойгу" and another
        # instance of the first label must not become three chapters.
        clean = re.sub(
            r"\b(?:причина|причини|дискусія|про|щодо)\b", " ",
            value.casefold(),
        )
        return " ".join(clean.split())

    first_label = selected[0][2]
    first_label = first_label[:1].upper() + first_label[1:]
    rows = [f"00:00 {first_label}"]
    seen = [concept(first_label)]
    for at, stamp, label, _confidence in selected:
        if at < 20:
            continue
        normalized = concept(label)
        if any(
            normalized == previous
            or (
                len(normalized) >= 12 and len(previous) >= 12
                and (normalized in previous or previous in normalized)
            )
            for previous in seen
        ):
            continue
        if len(rows) >= 10:
            break
        label = label[:1].upper() + label[1:]
        rows.append(f"{stamp} {label}")
        seen.append(normalized)
    # Require 3 different source-aligned chapters; duplicate story
    # labels are not independent chapters even if their times differ.
    return "\n".join(rows) if len(rows) >= 3 else ""


def preserve_outline_topics(
    description: str,
    report: dict[str, Any],
    *,
    max_body_bytes: int = 3900,
    max_topic_bullets: int = 6,
    current_title: str = "",
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
            topic = _topic_display_uk(item.get("topic"), current_title)
            if topic and topic.casefold() not in seen:
                seen.add(topic.casefold())
                unique.append(topic)

    if not unique:
        return source, []
    missing = [topic for topic in unique if topic.casefold() not in source.casefold()]
    if not missing:
        return source, []
    # Keep a concise representative spread across the WHOLE timeline.
    # The full evidence map stays in seo_evidence/*.json; unlisted topics
    # remain explicitly reported as omitted, rather than silently lost.
    keep_count = max(0, int(max_topic_bullets))
    if len(missing) > keep_count:
        if keep_count <= 0:
            selected_positions: set[int] = set()
        elif keep_count == 1:
            selected_positions = {len(missing) - 1}
        else:
            selected_positions = {
                round(index * (len(missing) - 1) / (keep_count - 1))
                for index in range(keep_count)
            }
        deferred = [
            topic for index, topic in enumerate(missing)
            if index not in selected_positions
        ]
        missing = [
            topic for index, topic in enumerate(missing)
            if index in selected_positions
        ]
    else:
        deferred = []

    # Preserve the core synopsis and every distinct grounded subject where
    # possible. Do not byte-truncate Cyrillic or silently remove topics.
    base = source
    footer = "\n\nІнші підтверджені теми розмов:\n"
    excluded: list[str] = list(deferred)
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
    # These surfaced during a real Shoigu 9:53 run. A title must contain a
    # concrete angle, not say merely that the video has opinions/discussion.
    weak_phrases = (
        r"\bвидео\s+с\s+обсуждени\w*",
        r"\bверсии\s+и\s+мнения\b",
        r"\bразные\s+точки\s+зрения\b",
        r"\bобсуждение\s+событи\w*\b",
    )
    for number, value in enumerate(values, 1):
        if any(re.search(pattern, value.casefold()) for pattern in weak_phrases):
            issues.append(
                f"A/B варіант {number} - загальна фраза замість конкретного сюжету."
            )
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

    # Compare meaningful topic words as well as surface string similarity.
    # A/B must represent different stories, not three paraphrases with the
    # same hook (observed on a real 50-minute RG video).
    common_words = {
        "россияне", "россия", "росії", "росіян", "россии",
        "украина", "україна", "война", "війна", "війни",
        "почему", "чому", "не", "але", "что", "что-то",
        "вони", "вона", "вони", "этот", "этого", "всі",
        "для", "как", "кого", "про", "или", "цей", "після",
        "раша", "гудбай", "чат", "рулетка",
    }
    content_stems = [
        {
            # Compare short event roots, not inflected endings:
            # "увольнение" and "уволен", "план" and "плану".
            word.replace("ь", "").replace("ъ", "").replace("ё", "е")[:4]
            for word in re.findall(
                r"[a-zа-яёіїєґ]{4,}", value.casefold()
            )
            if word not in common_words
        }
        for value in normal
    ]
    for left in range(3):
        for right in range(left + 1, 3):
            a, b = content_stems[left], content_stems[right]
            shared = a & b
            union = a | b
            overlap = len(shared) / len(union) if union else 0.0
            if len(shared) >= 3 and overlap >= 0.57:
                warning = (
                    f"Варіанти {left + 1} і {right + 1} "
                    "повторюють один сюжетний гачок."
                )
                if warning not in issues:
                    issues.append(warning)

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
            r"семей\w*\s+психолог\w*",
            r"сімейн\w*\s+психолог\w*",
            r"сімей\w*\s+психолог\w*",
        )
        # A phrase must occur inside ONE source quotation, never across
        # separate dialogue fragments or in model-written topic summaries.
        evidence_fragments = [
            _compact(item.get("evidence")).casefold()
            for block in report.get("blocks") or []
            for item in block.get("topics") or []
            if isinstance(item, dict)
        ]
        supported_family_topic = any(
            re.search(pattern, fragment, flags=re.UNICODE)
            for fragment in evidence_fragments
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
