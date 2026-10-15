"""Conservative source/title alignment checks for unpublished SEO drafts.

A file named <video_id>.srt alone is NOT proof it belongs to that video.
The checks below report obvious subject mismatches before invoking Ollama;
they never publish to YouTube or modify the source SRT.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# High-confidence named anchors from the project's public-affairs headlines.
# Aliases cover Russian/Ukrainian inflection/spelling differences.
_NAMED_SUBJECTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Шойгу", ("шойгу",)),
    ("Путін", ("путин", "путін")),
    ("Трамп", ("трамп", "trump")),
    ("Зеленський", ("зеленск", "зеленськ", "zelensk")),
    ("Лукашенко", ("лукашен",)),
    ("Білоусов", ("белоусов", "білоусов")),
    ("Пригожин", ("пригожин", "пригожин")),
    ("Медведєв", ("медведев", "медведєв")),
    ("Пєсков", ("песков", "пєсков")),
    ("Соловйов", ("соловьев", "соловйов")),
    ("Кадиров", ("кадыр", "кадир")),
    ("Сбербанк", ("сбербанк", "сбербан")),
    ("Вівальді", ("вивальди", "вівальді")),
)


@dataclass(frozen=True)
class Alignment:
    anchors: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.missing


def _text_words(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-zа-яёіїєґ0-9]+", str(text).casefold()))


def _has_alias(words: tuple[str, ...], aliases: tuple[str, ...]) -> bool:
    return any(
        word == alias or word.startswith(alias)
        for word in words for alias in aliases
    )


def _named_anchors(title: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    words = _text_words(title)
    return tuple(
        (label, aliases) for label, aliases in _NAMED_SUBJECTS
        if _has_alias(words, aliases)
    )


def check_title_against_transcript(
    title: str, transcript: str,
) -> Alignment:
    """Check strong named entities against ORIGINAL transcript text only.

    Never use a model-generated topic, copied video title, or synthesized
    description as source evidence. This is a narrow safety gate, not a
    general proof of source-video identity.
    """
    anchors = _named_anchors(title)
    words = _text_words(transcript)
    missing = tuple(
        label for label, aliases in anchors
        if not _has_alias(words, aliases)
    )
    return Alignment(tuple(label for label, _ in anchors), missing)


def check_title_variants_against_primary_subject(
    original_title: str, proposed_titles: list[str],
) -> Alignment:
    """Prevent A/B/C variants that all abandon a verified named subject.

    For an original title without one of the high-confidence named anchors,
    no inference about its topic is attempted by this function.
    """
    anchors = _named_anchors(original_title)
    if not anchors:
        return Alignment((), ())
    missing: list[str] = []
    for index, title in enumerate(proposed_titles, start=1):
        words = _text_words(title)
        if not any(_has_alias(words, aliases) for _, aliases in anchors):
            missing.append(f"варіант {index}")
    return Alignment(tuple(label for label, _ in anchors), tuple(missing))
