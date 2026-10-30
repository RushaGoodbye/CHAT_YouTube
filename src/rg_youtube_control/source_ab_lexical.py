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
) -> list[str]:
    """Return 3 individually sourced review titles, or [] if unprovable.

    An LLM's topic name is NEVER used as evidence. A source quotation must
    already have passed exact source verification; unverified blocks ignored.
    Final title quality is checked by the same public editorial validator.
    """
    from .dialogue_seo import ab_title_issues

    options: list[tuple[int, str, str]] = []
    seen_quotes: set[str] = set()
    for index, block in enumerate(report.get("blocks") or []):
        if not isinstance(block, dict) or block.get("verified") is False:
            continue
        for item in block.get("topics") or []:
            if not isinstance(item, dict):
                continue
            evidence = " ".join(str(item.get("evidence") or "").split())
            if len(evidence) < 16 or len(evidence) > 240:
                continue
            key = evidence.casefold()
            if key in seen_quotes:
                continue
            seen_quotes.add(key)
            labels = _grounded_labels(evidence)
            # Multiple mentions inside ONE utterance are not proof of three
            # different stories (e.g. "Шойгу коррупция оборона"). Select
            # just one concrete anchor per verbatim quotation.
            labels.sort(key=lambda label: label in _GENERIC)
            if labels:
                subject = labels[0]
                title = _FRAMES[0].format(subject=subject)
                if title.casefold() != current_title.strip().casefold():
                    options.append((index, subject, title))
        if len(options) >= 90:
            break

    if not options:
        return []
    # First try three different concrete subjects and widely spread timeline
    # anchors. A duplicate subject is not a new SEO story.
    distinct: list[tuple[int, str, str]] = []
    seen_subjects: set[str] = set()
    for candidate in sorted(options, key=lambda x: x[1] in _GENERIC):
        if candidate[1] not in seen_subjects:
            seen_subjects.add(candidate[1])
            distinct.append(candidate)
    if len(distinct) < 2:
        # Never manufacture a second event from three phrasings of one quote.
        return []

    # Trial triples must each have a unique, source-proven topic and strictly
    # pass the existing full-transcript evidence gate.
    if len(distinct) >= 3:
        for triple in sorted(
            combinations(distinct[:18], 3),
            key=lambda row: (
                sum(item[1] in _GENERIC for item in row),
                -len({item[0] for item in row}),
                -(max(item[0] for item in row) - min(item[0] for item in row)),
            ),
        ):
            titles = [
                _FRAMES[i].format(subject=triple[i][1])
                for i in range(3)
            ]
            if not ab_title_issues(titles, report):
                return titles

    # Two *different verified quotations* can make three useful A/B angles:
    # A = topic one, B = topic two, C = an explicitly attributed overview
    # identifying both topics as discussed. C NEVER implies that the topics
    # caused each other or describes an extra event.
    # This is NOT permitted for only one verified subject/quotation.
    for left, right in combinations(distinct[:18], 2):
        if left[1] == right[1]:
            continue
        first, second = left[1], right[1]
        angles = [
            _FRAMES[0].format(subject=first),
            _FRAMES[1].format(subject=second),
            f"{first} та {second}: про що говорили учасники?",
        ]
        if not ab_title_issues(angles, report):
            return angles
    return []
