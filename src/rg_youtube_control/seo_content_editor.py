"""Source-anchored Ukrainian SEO description, always review-only.

A source quotation establishes what was said, not whether it is true.
Do not publish automatically even if a description passes these checks.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

_GENERIC = (
    "у цьому випуску «раша гудбай» ведучий та співрозмовники обговорюють такі теми",
    "учасники чат-рулетки висловлюють власні думки та припущення",
    "дивіться повну розмову, щоб почути аргументи",
    "це попередній seo-чернетковий опис",
    "основні теми розмови", "обговорюються важливі питання",
)
_STOP = {"після", "цього", "щодо", "зараз", "дещо", "росія", "росії", "росіян",
         "україна", "україни", "тому", "якщо", "вони", "його", "вона", "тоді",
         "ведучий", "учасники", "співрозмовники", "говорять", "обговорюють",
         "сказав", "сказала", "питання", "розмова", "ситуація"}


def _words(s: str) -> set[str]:
    from .dialogue_seo import _cross_language_topic_word
    return {_cross_language_topic_word(w)[:5] for w in re.findall(
        r"[a-zа-яёіїєґ]{5,}", s.casefold()
    ) if w not in _STOP}


def grounded_description_issue(value: str, evidence: dict[str, Any]) -> str:
    description = " ".join(str(value or "").split())
    lower = description.casefold()
    if any(text in lower for text in _GENERIC):
        return "GENERIC_TEMPLATE_DESCRIPTION"
    if not (290 <= len(description) <= 950):
        return "DESCRIPTION_LENGTH"
    outside_quotes = re.sub(r"«[^»]*»", "", description)
    # Raw source quotations are audit evidence, not a finished Ukrainian
    # SEO description. They must never receive an editorial-quality PASS.
    quoted_characters = sum(len(q) for q in re.findall(r"«([^»]*)»", description))
    if quoted_characters > len(description) * 0.32:
        return "SOURCE_QUOTES_ARE_NOT_UKRAINIAN_DESCRIPTION"
    if re.search(r"(?i)\\b(?:співрозмовник каже|далі у відео звучить|в іншому фрагменті учасник)\\s*:", description):
        return "SOURCE_QUOTE_PREVIEW_NOT_SEO"
    if re.search(r"[ыэъё]", outside_quotes.casefold()):
        return "DESCRIPTION_MIXED_RUSSIAN"
    quotes = [str(t.get("evidence") or "").strip()
              for block in evidence.get("blocks") or []
              if isinstance(block, dict) and block.get("verified")
              for t in block.get("topics") or []
              if isinstance(t, dict) and t.get("evidence")]
    if not quotes:
        return "MISSING_SOURCE_QUOTATIONS"
    # Numeric quantities and exact proper names in SEO must be supported
    # verbatim by quoted source evidence. Don't turn quoted claims into facts.
    source = " ".join(quotes).casefold()
    numbers = set(re.findall(r"\b\d{2,}(?:[.,]\d+)?\b", description))
    if numbers - set(re.findall(r"\b\d{2,}(?:[.,]\d+)?\b", source)):
        return "UNSUPPORTED_NUMERIC_CLAIM"
    # Proper names need a source match, allowing Ukrainian/Russian morphology.
    proper = set(re.findall(r"(?<![.!?]\s)\b[А-ЯІЇЄҐ][а-яіїєґ]{4,}\b", outside_quotes))
    proper -= {"Раша", "Гудбай", "Україна", "Росія", "України", "Росії",
               "Збройних", "Силам", "Учасники", "Співрозмовники", "Ведучий",
               "Сьогодні", "Наприклад", "Співрозмовник", "Співрозмовниця",
               "Дискусія", "Розмова", "Гість", "Гостя", "Росіянин",
               "Росіянка", "Українці", "Росіяни", "Відео", "Також",
               "Зокрема", "Водночас", "Насамперед", "Далі", "Після",
               "Учасник", "Чоловік", "Жінка", "Репліки", "Проте"}
    source_stems = _words(source)
    if any(not (_words(name) & source_stems) for name in proper):
        return "UNSUPPORTED_NAMED_ENTITY"
    # A clear synopsis needs at least two concrete source-linked concepts.
    output_stems = _words(description)
    common = source_stems & output_stems
    if len(common) < 2:
        return "DESCRIPTION_NOT_SOURCE_SPECIFIC"
    if not re.search(r"\b(?:вважає|стверджує|говорить|пояснює|каже|припускає|запитує|на думку|за словами|зазначає|наголошує|розповідає|відповідає|обговорюють|запевняє|не розуміє|сумнівається|висловлює|звучить)\b", lower):
        return "MISSING_SPEAKER_ATTRIBUTION"
    return ""


def recover_source_description(
    *, report: dict[str, Any], current_title: str, model: str,
    chat: Callable[..., str], timeout: float = 85.0,
) -> tuple[str, str]:
    """One bounded repair from literal captions, with reject-on-uncertainty."""
    references = [
        {"time": str(block.get("start_stamp") or ""), "quotes": [
            str(t.get("evidence") or "") for t in block.get("topics") or []
            if isinstance(t, dict) and t.get("evidence")
        ]}
        for block in report.get("blocks") or []
        if isinstance(block, dict) and block.get("verified")
    ]
    messages = [
        {"role": "system", "content":
            "Ти український редактор. Пиши тільки JSON. ЖОДНИХ вигаданих фактів чи шаблонних вступів."},
        {"role": "user", "content": json.dumps({
            "task": "Створи конкретний SEO-опис 350–700 символів українською. "
                    "Поясни, що саме сказали або запитали люди. "
                    "Усі спірні заяви приписуй співрозмовникам, не як установлені факти. "
                    "Використай 2–4 різні деталі з наведених ДОСЛІВНИХ цитат. "
                    "Не додавай імена, місця, числа, події, яких у цитатах немає. "
                    "Не пиши про процес аналізу, не перераховуй абстрактні теми, "
                    "не пиши 'дивіться повну розмову'. "
                    "Поверни тільки JSON із ключем description.",
            "existing_title_is_not_factual_evidence":current_title,
            "verified_quotes":references
        },ensure_ascii=False)},
    ]
    try:
        raw=chat(messages,model=model,timeout=timeout,temperature=0.12,json_mode=True,num_ctx=16384)
        body=json.loads(str(raw).strip())
        value=str(body.get("description") or "").strip()
    except (ValueError,RuntimeError,TimeoutError,TypeError) as exc:
        return "",type(exc).__name__
    issue=grounded_description_issue(value,report)
    return (value,"") if not issue else ("",issue)


def literal_quote_description_preview(
    report: dict[str, Any], *, max_chars: int = 920,
) -> str:
    """A factual-neutral fallback: original quotations, never invented prose.

    This is a local PREVIEW only, not an accepted published description.
    """
    candidates = []
    seen = set()
    blocks = [b for b in report.get("blocks") or [] if isinstance(b,dict) and b.get("verified")]
    for bi, block in enumerate(blocks):
        for item in block.get("topics") or []:
            if not isinstance(item,dict):
                continue
            quote = " ".join(str(item.get("evidence") or "").split())
            if (35 <= len(quote) <= 200 and len(quote.split()) >= 7
                and quote.casefold() not in seen
                and not re.search(r"(?i)\\b(?:блядь|блять|нахуй|пиздец|хуй)\\b",quote)):
                seen.add(quote.casefold())
                candidates.append((bi,str(block.get("start_stamp") or "00:00:00"),quote))
    if len(candidates) < 3:
        return ""
    # Spread source passages over the timeline, do not select only the intro.
    choices=[]
    for target in (0,len(blocks)//2,len(blocks)-1):
        ranked=sorted(candidates,key=lambda q:(abs(q[0]-target),-len(q[2])))
        found=next((x for x in ranked if x not in choices),None)
        if found:
            choices.append(found)
    if len(choices)<3:
        return ""
    lines=[]
    for pos,(_,time,quote) in enumerate(sorted(choices,key=lambda a:a[0]),1):
        lead=("Співрозмовник каже" if pos==1 else
              "Далі у відео звучить" if pos==2 else
              "В іншому фрагменті учасник розмови говорить")
        lines.append(f"{lead}: «{quote}».")
    result=" ".join(lines)
    if len(result)<290:
        # Add context without fabricating who said each statement.
        result+=" Ці слова є репліками з відео, а не незалежно підтвердженими фактами."
    if not (290<=len(result)<=max_chars):
        return ""
    if any(q[2] not in result for q in choices):
        raise RuntimeError("SOURCE_QUOTE_PREVIEW_LOSS")
    return result