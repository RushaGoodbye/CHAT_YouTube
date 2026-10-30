"""Conservative Ukrainian A/B *review previews* from verified literal excerpts.

This is not translation of a whole transcript, an AI fact checker, or
permission to publish. It uses only exact quoted topic words, never infers
actions, causes, events or a relation between two named entities.
"""
from __future__ import annotations

import re
from itertools import combinations
from typing import Any

# Each Ukrainian topical label is tied to a recognizable source-language root.
# Labels identify the subject alone: no claims or changed factual meaning.
_TOPIC_ROOTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Корупція", ("корруп", "коруп")),
    ("Мобілізація", ("мобилиз", "мобіліз", "мобилиз")),
    ("Бензин", ("бензин",)),
    ("Війна", ("войн", "війн", "вийна")),
    ("Санкції", ("санкц",)),
    ("Шойгу", ("шойгу",)),
    ("Путін", ("путин", "путін")),
    ("Трамп", ("трамп",)),
    ("Ціни", ("цены", "ценам", "ценник", "ціни", "цін")),
    ("Пенсії", ("пенси", "пенсі")),
    ("Зарплати", ("зарплат",)),
    ("Економіка", ("экономик", "економік", "економик")),
    ("Влада", ("власт", "влад")),
    ("Армія", ("армия", "армию", "арми", "армі")),
    ("Оборона", ("оборон",)),
    ("Дрони", ("дрон",)),
    ("Вибухи", ("взрыв", "вибух")),
    ("Газ", ("газ",)),
    ("Фронт", ("фронт",)),
    ("Крим", ("крым", "крим")),
    ("Пропаганда", ("пропаганд",)),
    ("НАТО", ("нато",)),
    ("США", ("сша",)),
    ("Європа", ("европ", "європ")),
    ("Україна", ("украин", "україн")),
    ("Росія", ("росси", "росі")),
    ("Податки", ("налог", "податк")),
    ("Зброя", ("оруж", "збро")),
    ("Президент", ("президент",)),
)
_GENERIC = {"Війна", "Росія", "Україна", "США", "Президент", "Європа"}
_FRAMES = (
    "{subject}: що говорять співрозмовники?",
    "{subject}: про що йдеться у чат-рулетці?",
    "{subject}: що прозвучало під час розмови?",
)


def _grounded_labels(quote: str) -> list[str]:
    words = re.findall(r"[а-яёіїєґa-z]+", quote.casefold())
    # Root matching must begin at the source word start; substring matching
    # in arbitrary words can turn entirely unrelated content into a subject.
    # Very short stems are ambiguous: "газета" is not a discussion of gas.
    # Match gas inflections as complete words rather than matching "газ*".
    gas_words = {"газ", "газа", "газу", "газом", "газе", "газів", "газові"}
    return [
        label
        for label, aliases in _TOPIC_ROOTS
        if (
            any(word in gas_words for word in words)
            if label == "Газ"
            else any(word.startswith(alias) for word in words for alias in aliases)
        )
    ]


def source_grounded_ukrainian_ab(
    report: dict[str, Any], current_title: str = "",
    *, diagnostics: dict[str, Any] | None = None,
) -> list[str]:
    """Return 3 individually sourced review titles, or [] if unprovable.

    An LLM's topic name is NEVER used as evidence. A source quotation must
    already have passed exact source verification; unverified blocks ignored.
    Final title quality is checked by the same public editorial validator.
    """
    from .dialogue_seo import ab_title_issues

    # Diagnostic values are COUNTS/CODES ONLY. No private captions, words,
    # titles, topic labels, user details or paths are ever included.
    counters: dict[str, int] = {}
    def count(reason: str) -> None:
        counters[reason] = counters.get(reason, 0) + 1

    def failure(issues: list[str]) -> None:
        for issue in issues:
            if "підтверджених тематичних" in issue or "дослівні цитати" in issue or "непідтверджен" in issue:
                count("unsupported_subject")
            elif "повторюють" in issue or "сюжетну опору" in issue:
                count("repeated_hook")
            elif "20-100" in issue or "рівно 3" in issue:
                count("title_count_or_length")
            elif "не українською" in issue:
                count("non_ukrainian")
            else:
                count("other_editorial_rejection")

    def publish_diagnostics() -> None:
        if diagnostics is not None:
            diagnostics.update({
                "source_quote_count": quote_id,
                "distinct_root_count": len(subject_quotes),
                "failure_counts": dict(sorted(counters.items())),
            })

    # Collect every safely recognized root but attach each to its original
    # distinct literal quotation. One quotation may propose alternatives,
    # yet it can substantiate at most ONE selected A/B subject.
    # Previous greedy "first root in each quote" discarded legitimate second
    # topics in short real videos when all quotations mentioned the same name.
    subject_quotes: dict[str, list[tuple[int, int]]] = {}
    seen_quotes: set[str] = set()
    quote_id = 0
    for block_index, block in enumerate(report.get("blocks") or []):
        if not isinstance(block, dict) or block.get("verified") is False:
            continue
        for item in block.get("topics") or []:
            if not isinstance(item, dict):
                continue
            evidence = " ".join(str(item.get("evidence") or "").split())
            if not (16 <= len(evidence) <= 240):
                continue
            key = evidence.casefold()
            if key in seen_quotes:
                continue
            seen_quotes.add(key)
            labels = _grounded_labels(evidence)
            if not labels:
                continue
            for subject in set(labels):
                subject_quotes.setdefault(subject, []).append(
                    (quote_id, block_index)
                )
            quote_id += 1
            if quote_id >= 90:
                break
        if quote_id >= 90:
            break

    if len(subject_quotes) < 2:
        count("fewer_than_two_source_roots")
        publish_diagnostics()
        return []

    # Prefer concrete topics; repeated source evidence may increase confidence
    # but a recurring subject alone is not a second event.
    subjects = sorted(
        subject_quotes,
        key=lambda subject: (
            subject in _GENERIC,
            min(index for index, _ in subject_quotes[subject]),
            -len(subject_quotes[subject]), subject,
        ),
    )[:18]

    def anchored_selection(
        names: tuple[str, ...],
    ) -> tuple[tuple[int, int], ...] | None:
        """Pick distinct verbatim excerpts for each subject, or reject."""
        def choose(
            position: int, used: set[int], picked: list[tuple[int, int]],
        ) -> tuple[tuple[int, int], ...] | None:
            if position == len(names):
                return tuple(picked)
            for quote_and_block in subject_quotes[names[position]]:
                quote, _ = quote_and_block
                if quote in used:
                    continue
                result = choose(
                    position + 1, used | {quote}, picked + [quote_and_block],
                )
                if result is not None:
                    return result
            return None
        return choose(0, set(), [])

    triples = sorted(
        combinations(subjects, 3),
        key=lambda names: (
            sum(name in _GENERIC for name in names),
            -sum(len(subject_quotes[name]) for name in names),
        ),
    )
    for names in triples:
        assignment = anchored_selection(names)
        if assignment is None:
            count("no_distinct_quote_assignment")
            continue
        titles = [
            _FRAMES[i].format(subject=names[i])
            for i in range(3)
        ]
        issues = ab_title_issues(titles, report)
        if not issues:
            publish_diagnostics()
            return titles
        failure(issues)

    # Two separately supported subjects also support an attributed overview;
    # it is not a third new story. Require *two distinct* source quotations.
    for names in combinations(subjects, 2):
        if anchored_selection(names) is None:
            count("no_distinct_quote_assignment")
            continue
        first, second = names
        angles = [
            _FRAMES[0].format(subject=first),
            _FRAMES[1].format(subject=second),
            f"{first} та {second}: про що говорили учасники?",
        ]
        issues = ab_title_issues(angles, report)
        if not issues:
            publish_diagnostics()
            return angles
        failure(issues)
    publish_diagnostics()
    return []
