"""Conservative ASR name evidence for editorial drafts (never rewrite source).

Whisper may render 'Шойгу' as 'шагу' or 'шайгу'. Such ordinary-language
lookalikes are NOT sufficient on their own to establish a named subject.
Require a literal original mention plus repeated contextually supported ASR
variants, or repeated literal mentions. Never synthesize a quotation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_LITERAL_SHOIGU = re.compile(r"(?<!\w)шойгу(?!\w)", re.IGNORECASE)
_SHOIGU_ASR = re.compile(r"(?<!\w)(?:шагу|шогу|шайгу)(?!\w)", re.IGNORECASE)
_CONTEXT = (
    "уволь", "звіль", "звиль", "отстав", "відстав",
    "корруп", "коруп", "взят", "посад", "должност",
    "министр", "міністр", "путин", "путін",
    "мчс", "минобор", "замест", "команд",
)


@dataclass(frozen=True)
class ShoiguEvidence:
    literal_mentions: int
    contextual_asr_mentions: int

    @property
    def supported_mentions(self) -> int:
        return self.literal_mentions + self.contextual_asr_mentions

    @property
    def source_name_supported(self) -> bool:
        # One proper-name mention anchors a possible ASR variant; without
        # that original proof we keep uncertain phonetic matches for review.
        return self.literal_mentions >= 2 or (
            self.literal_mentions >= 1 and self.contextual_asr_mentions >= 1
        )


def shoigu_source_evidence(original_text: str) -> ShoiguEvidence:
    """Only inspect exact lexical words in the ORIGINAL transcript text."""
    source = str(original_text or "").casefold()
    exact = len(_LITERAL_SHOIGU.findall(source))
    contextual = sum(
        any(stem in source[max(0, m.start() - 90):m.end() + 90]
            for stem in _CONTEXT)
        for m in _SHOIGU_ASR.finditer(source)
    )
    return ShoiguEvidence(exact, contextual)
