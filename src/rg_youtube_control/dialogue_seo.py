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
                if item["verified"]:
                    cache_hits += 1
                else:
                    # An invalid old cache entry must never suppress a fresh
                    # source-grounded attempt for a real transcript block.
                    item = None
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
            # A single invalid model response must not silently lose an entire
            # chronological block. Retry once with a shorter, exact-quote
            # extraction prompt. The same strict source verifier applies.
            # If the quote still cannot be proven, keep it unverified.
            if not item["verified"] and len(block["text"].strip()) >= 100:
                retry_prompt = (
                    "Віднови ОДНУ тему лише з цього фрагмента. "
                    "Поверни JSON з topics: [{topic, summary_uk, evidence}]. "
                    "evidence — ДОСЛІВНА послідовність від 8 до 240 символів "
                    "з наведеного тексту, НЕ перефразовуй і не перекладай її. "
                    "topic та summary_uk українською. "
                    "Якщо немає точної цитати, topics=[].\n\n"
                    + block["text"][:3600]
                )
                try:
                    raw_retry = chat(
                        [
                            {"role": "system", "content": "Лише валідний JSON з точною цитатою."},
                            {"role": "user", "content": retry_prompt},
                        ],
                        model=model, timeout=timeout, temperature=0.0,
                        json_mode=True,
                    )
                    retried = _validate_topics(
                        json.loads(str(raw_retry).strip()), block,
                    )
                    if retried["verified"]:
                        item = retried
                except (ValueError, RuntimeError, TimeoutError, TypeError, OSError):
                    pass
            if not item["verified"]:
                # Final constrained rescue: let the model author a *topic*
                # but NEVER the quotation. Pin one literal meaningful source
                # line, and require its unchanged use. This is attempted only
                # after two unsuccessful responses and never relaxes source
                # matching or silently approves an unverified block.
                source_lines = [
                    _compact(line)
                    for line in block["text"].splitlines()
                    if len(_compact(line)) >= 40
                ]
                if source_lines:
                    quote = max(
                        source_lines,
                        key=lambda line: (
                            len(set(re.findall(r"\w+", line.casefold()))),
                            len(line),
                        ),
                    )[:200].rsplit(" ", 1)[0].rstrip(" ,.;:")
                    if len(quote) >= 30:
                        rescue_prompt = (
                            "Ти не створюєш цитати. Поверни JSON, "
                            "topics: [{topic, summary_uk, evidence}]. "
                            "Тема та коротка теза українською лише про те, "
                            "що прямо сказано в наведеній дослівній репліці. "
                            "Значення evidence ОБОВ'ЯЗКОВО скопіюй без "
                            "змін, пропусків або перекладу. Якщо тема не "
                            "зрозуміла, topics=[].\n"
                            f"ДОСЛІВНА РЕПЛІКА: {quote}\n"
                            f"ДОСЛІВНИЙ evidence: {json.dumps(quote, ensure_ascii=False)}"
                        )
                        try:
                            rescued_raw = chat(
                                [
                                    {"role": "system", "content": "JSON. Без доданих фактів."},
                                    {"role": "user", "content": rescue_prompt},
                                ],
                                model=model, timeout=timeout,
                                temperature=0.0, json_mode=True,
                            )
                            rescued = _validate_topics(
                                json.loads(str(rescued_raw).strip()), block,
                            )
                            if rescued["verified"]:
                                item = rescued
                        except (ValueError, RuntimeError, TimeoutError,
                                TypeError, OSError):
                            pass
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


def distinct_evidence_topics(report: dict[str, Any]) -> list[dict[str, str]]:
    """Conservatively group repeated claims without inventing new stories.

    Only verbatim evidence is eligible. Identical or highly overlapping
    claims collapse into one; different quotations remain independent.
    """
    distinct: list[dict[str, str]] = []
    signatures: list[set[str]] = []
    for block in report.get("blocks") or []:
        if block.get("verified") is False:
            continue
        for item in block.get("topics") or []:
            if not isinstance(item, dict):
                continue
            evidence = _compact(item.get("evidence"))
            topic = _compact(item.get("topic"))
            if not evidence or not topic:
                continue
            words = {
                token[:6] for token in re.findall(r"\w+", evidence.casefold()) if len(token) >= 5 or token.isdigit()
            }
            if not words:
                continue
            repeated = any(
                words == seen or (
                    len(words & seen) >= 4
                    and len(words & seen) / min(len(words), len(seen)) >= 0.85
                )
                for seen in signatures
            )
            if repeated:
                continue
            signatures.append(words)
            distinct.append({
                "topic": topic,
                "evidence": evidence,
                "summary_uk": _compact(item.get("summary_uk")),
                "start_stamp": str(block.get("start_stamp") or ""),
            })
    return distinct


def evidence_outline_text(report: dict[str, Any]) -> str:
    """Compact all verified block notes for final model, without omission."""
    lines: list[str] = []
    for topic in distinct_evidence_topics(report):
        lines.append(
            f"[{topic['start_stamp']}] ТЕМА: {topic['topic']} | "
            f"ТЕЗА: {topic['summary_uk']} | ЦИТАТА: {topic['evidence']}"
        )
    for block in report.get("blocks") or []:
        stamp = str(block.get("start_stamp") or "")
        topics = block.get("topics") or []
        if not topics or block.get("verified") is False:
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
    max_topic_bullets: int = 6,
) -> tuple[str, list[str]]:
    """Add missing grounded topics without silently discarding the outline.

    Return omitted topics for manual review if even the topic list cannot fit.
    Service links and three hashtags are appended later by safe_description_fix.
    """
    source = str(description or "").strip()
    unique: list[str] = []
    seen: set[str] = set()
    # Prefer citation-grounded, deduplicated subjects. Legacy reports with
    # no evidence retain their historical topic-list behavior.
    grounded = distinct_evidence_topics(report)
    if grounded:
        candidates = [item["topic"] for item in grounded]
    else:
        candidates = [
            _compact(item.get("topic"))
            for block in report.get("blocks") or []
            if block.get("verified") is not False
            for item in block.get("topics") or []
            if isinstance(item, dict)
        ]
    for topic in candidates:
        if topic and topic.casefold() not in seen:
            seen.add(topic.casefold())
            unique.append(topic)

    if not unique:
        return source, []
    # Avoid restating the synopsis as six near-identical bullet points.
    # Never discard topics from the archived evidence report itself.
    def subject_words(value: str) -> set[str]:
        stop = {"про", "щодо", "причини", "причина", "дискусія", "обговорення",
                "питання", "зміни", "посади", "відповідальність", "розмова",
                "російській", "росії", "армії", "та", "або", "щодо"}
        return {word[:5] for word in re.findall(r"\w{5,}", value.casefold())
                if word not in stop}

    synopsis_words = subject_words(source.split("Інші підтверджені теми розмов:", 1)[0])
    missing: list[str] = []
    selected_keys: list[set[str]] = []
    for topic in unique:
        keys = subject_words(topic)
        # Shoigu dismissal and corruption are already covered by the synopsis.
        if topic.casefold() in source.casefold():
            continue
        if grounded and keys and len(keys & synopsis_words) >= min(2, len(keys)):
            continue
        if grounded and keys and any(len(keys & previous) >= min(2, len(keys), len(previous))
                        for previous in selected_keys):
            continue
        missing.append(topic)
        selected_keys.append(keys)

    if grounded and missing:
        # Source labels are not automatically suitable as public prose.
        # A topic already represented by the same named subject and event
        # in the synopsis is not a genuinely additional story.
        synopsis_norm = source.casefold()
        if "шойгу" in synopsis_norm and (
            "звільнен" in synopsis_norm or "посад" in synopsis_norm
        ):
            missing = [topic for topic in missing if not (
                ("шойгу" in topic.casefold() or "шагу" in topic.casefold())
                and any(stem in topic.casefold() for stem in (
                    "увольнен", "звільнен", "причин", "посад", "увільнен"
                ))
            )]
    if grounded and missing:
        # Uncertain ASR labels must not be promoted to the public description.
        # A verified quotation stays in the private evidence map for review.
        missing = [topic for topic in missing if not re.search(
            r"(?i)шагу|увільнен|стратегічн.{0,16}неадекват", topic
        )]
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



def _cross_language_topic_word(word: str) -> str:
    """Conservative bilingual *topic* normalization for verified quotations.

    A normalized match is only a reason to consider a Ukrainian lexical
    variant: it NEVER overrides title-language, quote provenance, factual
    or editorial review gates. No external network, model or API quota.
    """
    w = str(word or "").casefold().translate(str.maketrans({
        "і": "и", "ї": "и", "є": "е", "ґ": "г", "ё": "е",
        "ы": "и", "э": "е",
    }))
    # All matched prefixes in a family share the same canonical five-letter
    # root; this also tolerates plural/declension in Ukrainian and Russian.
    families = (
        (("коруп", "корруп"), "корруп"),
        (("росі", "росси", "россий", "росия"), "росси"),
        (("війн", "вийн", "войн"), "война"),
        (("звільн", "звилн", "увольн", "уволен"), "уволн"),
        (("посад", "должн", "должност"), "должн"),
        (("змін", "змин", "смен"), "смена"),
        (("рішен", "ришен", "решен"), "решен"),
        (("влад", "власт"), "власт"),
        (("путін", "путин"), "путин"),
        (("оборон",), "оборо"),
        (("пенсі", "пенси"), "пенси"),
        (("зарплат",), "зарпл"),
        (("бензин",), "бензи"),
        (("пальн", "топлив"), "топли"),
        (("цін", "цин", "цен"), "ценыx"),
        (("подорожч", "подорожа"), "дорож"),
        (("мобілі", "мобили"), "мобил"),
        (("крим", "крым"), "крымx"),
        (("релігі", "религи"), "религ"),
        (("пропаганд",), "пропа"),
        (("армі", "арми", "армия"), "армия"),
        (("вибух", "взрыв"), "взрив"),
        (("президент",), "прези"),
        (("стратег",), "страт"),
        (("кадров",), "кадро"),
        (("санкц",), "санкц"),
    )
    for variants, canonical in families:
        if any(w.startswith(alias.translate(str.maketrans({"і": "и", "ї": "и", "є": "е"}))) for alias in variants):
            return canonical
    return w


# These are *exact, fixed* editorial-question frames, not source facts.
# Recognize only complete frame matches. A new event, attribution or claim in
# the subject is still checked against verified quotations word by word.
_NEUTRAL_SOURCE_AB_FRAMES = (
    re.compile(r"^(.+?): що говорять співрозмовники\?$", re.I),
    re.compile(r"^(.+?): про що йдеться у чат-рулетці\?$", re.I),
    re.compile(r"^(.+?): що прозвучало під час розмови\?$", re.I),
    re.compile(r"^(.+?): про що говорили учасники\?$", re.I),
    re.compile(r"^(.+?): що обговорили співрозмовники\?$", re.I),
)


def _neutral_source_ab_subject(title: str) -> str | None:
    """Extract asserted subject only for recognized nonfactual question text."""
    for frame in _NEUTRAL_SOURCE_AB_FRAMES:
        match = frame.fullmatch(str(title or "").strip())
        if match:
            return match.group(1)
    return None


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

    # Extra offline evidence-independent duplicate detector (RapidFuzz/MIT).
    # It only rejects repeated hooks; it cannot turn unsupported text into
    # grounded metadata or create a missing A/B story.
    from .seo_free_quality import repeated_ab_event_pairs
    for left, right in repeated_ab_event_pairs(values):
        reason = (
            f"Варіанти {left + 1} і {right + 1} повторюють один сюжетний гачок."
        )
        if reason not in issues:
            issues.append(reason)

    # Generic editorial labels are not a useful or factual third A/B hook.
    # They used to pass the offline gate and reach the real GUI preview.
    generic_hook = re.compile(
        r"(?i)(?:дискусси[яи]\s+о\s+причин|"
        r"дискусі[яї]\s+про\s+причин|"
        r"обсужден[иия]+\s+причин|"
        r"внутренн(?:ие|их)\s+причин|"
        r"версии\s+и\s+факты)"
    )
    asr_misspelling = re.compile(
        r"(?i)\bшогу\b|\bшагу\b|\bшаг[аи]\s+на\s+пути\b"
    )
    irrelevant_hook = re.compile(
        r"(?i)\bответ\s+на\s+вопрос\b|"
        r"\bпочему\s+не\s+ответил[иа]?\b"
    )
    # The model may ignore a Ukrainian prompt and return Russian headlines.
    # Reject such drafts explicitly instead of trusting the prompt wording.
    for index, value in enumerate(values, 1):
        folded = value.casefold()
        russian_grammar = len(re.findall(
            r"\b(?:почему|что|это|увольнение|уволили|коррупция|"
            r"россияне|российские|рассказывают|обсуждают|говорят|"
            r"всё|все|который|которые|вопросы|ответы|и|или|"
            r"военная|стратегия|происходит|причины|отставка)\b",
            folded,
        ))
        from .seo_free_quality import russian_language_signal
        if (
            re.search(r"[ыэъё]", folded)
            or russian_grammar >= 2
            or russian_language_signal(value)
        ):
            issues.append(f"A/B варіант {index} не українською мовою.")

    for index, value in enumerate(values, 1):
        if asr_misspelling.search(value):
            issues.append(
                f"A/B варіант {index} містить помилку розпізнавання або штучний сюжетний гачок."
            )
        if irrelevant_hook.search(value):
            issues.append(
                f"A/B варіант {index} є загальною реплікою замість змістовної теми."
            )

    for index, value in enumerate(values, 1):
        if generic_hook.search(value):
            issues.append(
                f"A/B варіант {index} надто загальний і не містить конкретного сюжетного гачка."
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
    # Three different headlines can evade pairwise Jaccard by shuffling
    # peripheral wording while all reuse one dominant event word. This is
    # exactly what happened in the operator's real Shoigu A/B preview:
    # all three repeated "стратегия" and two pairs reused another event.
    # Report this as a review problem and trigger independent-hook recovery.
    common_core = set.intersection(*content_stems) if content_stems else set()
    # A recurring protagonist is not evidence of repeating the same hook.\n    # Compare the event/claim instead of penalizing all titles about Shoigu.\n    common_core -= {"росс", "росі", "укра", "война", "війна", "шойг"}
    if common_core:
        repeated_pairs = sum(
            bool((content_stems[left] & content_stems[right]) - common_core)
            for left, right in ((0, 1), (0, 2), (1, 2))
        )
        if repeated_pairs >= 2:
            issues.append(
                "Усі три A/B назви повторюють одну основну сюжетну опору."
            )

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
        # Only literal source excerpts can support title claims. Model-written
        # topic labels and summaries are *not* independent evidence.
        evidence_fragments = [
            _compact(item.get("evidence")).casefold()
            for block in report.get("blocks") or []
            if isinstance(block, dict) and block.get("verified") is not False
            for item in block.get("topics") or []
            if isinstance(item, dict)
        ]
        source = " ".join(evidence_fragments).translate(
            str.maketrans({"і": "и", "ї": "и", "є": "е", "ґ": "г"})
        )
        stems = {
            _cross_language_topic_word(word)[:5]
            for word in re.findall(r"[a-zа-яё0-9]{5,}", source)
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
            # Avoid treating the *fixed neutral question* as a new event:
            # "йдеться", "рулетці", "говорили" are formatting, not claims.
            # For all other titles the full original strict check remains.
            neutral_subject = _neutral_source_ab_subject(value)
            factual_text = neutral_subject if neutral_subject is not None else value
            words = re.findall(
                r"[a-zа-яё0-9]{5,}",
                factual_text.casefold().translate(
                    str.maketrans({"і": "и", "ї": "и", "є": "е", "ґ": "г"})
                ),
            )
            meaningful = [
                word for word in words
                if word not in {
                    "чатрулетка", "рулетка", "рашагудбай",
                    "россияне", "россия", "российск",
                    "кажуть", "говорять", "учасники", "розмови",
                    "спиврозмовники", "питання", "думки", "версии",
                    "обговорюють", "пояснюють", "скільки",
                    # Non-factual editorial question scaffolding is not a
                    # claimed subject and must not be counted as an
                    # unsupported event merely because nobody said the same
                    # interrogative wording verbatim.
                    "оцінки", "оцінка", "пролунали", "звучать",
                    "прозвучали", "співрозмовники", "співрозмовників",
                    "переглядачі", "глядачі", "називають",
                    "вважають", "припускають", "відповідають",
                    "дискусія", "обговорення", "розповідають",
                    "якими", "насправді", "запитують",
                    "участники", "собеседники", "обсуждают",
                    "оценки", "мнения", "рассказывают",
                }
            ]
            if neutral_subject is not None:
                # This exception applies only to subject-only editorial
                # templates. ALL substantial nouns/names still need source
                # support; a single matching name must not launder claims.
                # Allow single short canonical labels only when they appear
                # verbatim among verified quotations.
                subject_words = re.findall(
                    r"[a-zа-яёіїєґ]+", neutral_subject.casefold()
                )
                stop = {"та", "і", "й", "про", "щодо", "на", "у", "в", "за", "з"}
                unsupported = [
                    word for word in subject_words
                    if word not in stop and (
                        _cross_language_topic_word(word)[:5] not in stems
                        if len(word) >= 5
                        else not any(
                            re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)",
                                      quote, re.I)
                            for quote in evidence_fragments
                        )
                    )
                ]
                if unsupported:
                    issues.append(
                        f"A/B варіант {index} не має підтверджених тематичних слів."
                    )
            elif meaningful and not any(
                _cross_language_topic_word(word)[:5] in stems for word in meaningful
            ):
                issues.append(
                    f"A/B варіант {index} не має підтверджених тематичних слів."
                )
            # A single shared word ("война") must not launder a novel
            # assertion ("война переходит в новую фазу"). This is a
            # conservative editorial warning: lexical differences may be
            # legitimate paraphrases and are never called proven false.
            # Above, neutral question/attribution words are already excluded:
            # only factual subjects are checked against the exact quotes.
            source_only = [
                word for word in meaningful
                if _cross_language_topic_word(word)[:5] not in stems
                and word not in {
                    "почему", "который", "которые", "говорят",
                    "рассказ", "вопросы", "ответы", "выпуск",
                    "сегодня", "видео", "история", "будущее",
                }
            ]
            if len(source_only) >= 3 and len(source_only) * 2 >= len(meaningful):
                issues.append(
                    f"A/B варіант {index} містить кілька формулювань "
                    "без опори на дослівні цитати; перевірити заявлені події."
                )
    return issues
