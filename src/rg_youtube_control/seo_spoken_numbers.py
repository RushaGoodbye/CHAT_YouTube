"""Conservative spoken-number grounding in Russian/Ukrainian captions.

Supports simple cardinals/ordinals and compound 21..99. Recognized values
support an editorial candidate; they do NOT assert factual truth.
"""
from __future__ import annotations

import re


def _normalize(word: str) -> str:
    return word.casefold().replace("ё", "е").replace("ґ", "г").replace("'", "").replace("’", "").replace("ʼ", "")


_UNITS = {
    0: ("ноль", "нуль", "нулевой", "нульовий"),
    1: ("один", "одна", "первый", "перший", "один"),
    2: ("два", "две", "дві", "второй", "другий"),
    3: ("три", "третий", "третій"),
    4: ("четыре", "чотири", "четвертый", "четвертий"),
    5: ("пять", "пятеро", "пятый", "пятий"),
    6: ("шесть", "шість", "шестой", "шостий"),
    7: ("семь", "сім", "седьмой", "сьомий"),
    8: ("восемь", "вісім", "восьмой", "восьмий"),
    9: ("девять", "девять", "девятий", "девятый", "дев'ять"),
}
_TENS = {
    10: ("десять", "десятый", "десятий"),
    11: ("одиннадцать", "одинадцять", "одиннадцатый"),
    12: ("двенадцать", "дванадцять", "двенадцатый"),
    13: ("тринадцать", "тринадцять"),
    14: ("четырнадцать", "чотирнадцять"),
    15: ("пятнадцать", "пятнадцять"),
    16: ("шестнадцать", "шістнадцять"),
    17: ("семнадцать", "сімнадцять"),
    18: ("восемнадцать", "вісімнадцять"),
    19: ("девятнадцать", "дев'ятнадцять"),
    20: ("двадцать", "двадцять", "двадцатый", "двадцятий"),
    30: ("тридцать", "тридцять", "тридцатый"),
    40: ("сорок", "сороковой", "сороковий"),
    50: ("пятьдесят", "п'ятдесят", "пятидесятый"),
    60: ("шестьдесят", "шістдесят"),
    70: ("семьдесят", "сімдесят"),
    80: ("восемьдесят", "вісімдесят"),
    90: ("девяносто", "дев'яносто", "девяностый", "дев'яностий"),
    100: ("сто", "сотый", "сотий"),
}
_WORDS = {
    _normalize(word): number
    for group in (_UNITS, _TENS)
    for number, variants in group.items()
    for word in variants
}


def grounded_number_values(source: str) -> set[str]:
    """Return only numbers literally printed or clearly spoken in source."""
    values = set(re.findall(r"(?<!\w)\d+(?!\w)", source))
    words = [_normalize(token) for token in re.findall(r"[^\W\d_]+(?:['’ʼ][^\W\d_]+)?", source, re.UNICODE)]
    for i, word in enumerate(words):
        val = _WORDS.get(word)
        if val is None:
            continue
        if i > 0 and 1 <= val <= 9 and _WORDS.get(words[i - 1]) in range(20, 100, 10):
            # An ordinal unit from a compound does not establish a separate
            # fuel grade: ninety-fifth is 95, not an independent fifth.
            continue
        if val in range(20, 100, 10) and i + 1 < len(words):
            unit = _WORDS.get(words[i + 1])
            if unit is not None and 1 <= unit <= 9:
                # "девяносто пятый" supports 95, NOT an
                # independent 90. Avoid partial-number hallucinations.
                values.add(str(val + unit))
                continue
        values.add(str(val))
    return values
