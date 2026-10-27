"""RG SEO Engine 1.0: independent, offline, source-bound SEO draft generator.

No YouTube writes; no UI or application database dependencies.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from .seo_source_excerpt import select_source_excerpt


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



# General channel words are not evidence of the video subject. Titles can be
# rephrased, but must preserve at least one non-generic topic from the current
# public headline if that headline has multiple meaningful topic words.
_TOPIC_STOP = {
    "раша", "гудбай", "россия", "россии", "россию", "россияне",
    "русские", "россиянин", "ютуб", "youtube", "канал", "чат",
    "рулетка", "против", "после", "снова", "опять", "новости",
    "сегодня", "сейчас", "теперь", "видео", "стрим", "отвечает",
    "почему", "когда", "какие", "какой", "можно", "нужно",
    "будет", "были", "было", "делают", "делает", "говорят",
    "сказал", "сказала", "что", "это", "все", "вот", "еще",
    "путин", "putin",
}


_TOPIC_ALIASES = (
    # Conservative equivalences, not general semantic inference. This
    # prevents false blocks such as "не менять" versus "без изменений".
    (("войн", "війн", "виин"), "war"),
    (("измен", "менят", "менял", "меняе", "меняю", "перемен", "змін"), "change"),
    (("фантаз",), "fantasy"),
    (("рыбак", "рыбал", "рыбац", "рибал"), "fishing"),
    (("джед",), "jedi"),
    (("налог", "подат"), "tax"),
    (("бензин", "топлив", "пальн", "палив"), "fuel"),
    (("учител", "вчител", "педагог", "преподав"), "teacher"),
    (("школ",), "school"),
    (("осужден", "судим", "засуджен"), "convicted"),
    (("преступ", "злочин"), "crime"),
)


def _topic_roots(value: str) -> set[str]:
    # Fold limited RU/UA inflections and closely equivalent lexical stems.
    # Ignore numerical durations, channel branding and general filler.
    words = _words(value.replace("ё", "е").replace("і", "и")
                   .replace("ї", "и").replace("є", "е"))
    roots = set()
    for word in words:
        if word in _TOPIC_STOP or len(word) < 5 or word.isdigit():
            continue
        canonical = next(
            (name for prefixes, name in _TOPIC_ALIASES
             if any(word.startswith(prefix) for prefix in prefixes)),
            word[:6],
        )
        roots.add(canonical)
    return roots


def _check_source_video(current_title: str, source: str) -> None:
    from .seo_source_alignment import check_title_against_transcript
    match = check_title_against_transcript(current_title, source)
    if match.missing:
        raise ValueError("SOURCE_VIDEO_MISMATCH: named title anchor missing")
    # Original metadata alone cannot prove captions belong to the video;
    # guard against obvious title/source swaps BEFORE paying for inference.
    roots = _topic_roots(current_title)
    if len(roots) >= 2 and not roots.intersection(_topic_roots(source)):
        raise ValueError("SOURCE_VIDEO_MISMATCH: title topic absent from transcript")


def _check_editorial_title(current_title: str, title: str, source: str) -> None:
    # A subject change is more important than a generic headline defect.
    specific_words = _topic_roots(title)
    original = _topic_roots(current_title)
    source_roots = _topic_roots(source)
    if len(original) >= 2 and original.intersection(source_roots):
        if not original.intersection(specific_words):
            raise ValueError("SEO_TOPIC_MISMATCH: title abandons original subject")
    if len(specific_words) >= 3 and not specific_words.intersection(source_roots):
        raise ValueError("SEO_TOPIC_MISMATCH: generated headline absent from transcript")
    if len(specific_words) < 3:
        # Two named, source-verified subjects can be an excellent precise
        # headline: e.g., РЫБАК И ДЖЕДАЙ. Generic two-word paraphrases
        # without distinct anchors from the original are still rejected.
        if len(specific_words.intersection(original)) < 2:
            raise ValueError("Generic non-editorial headline")
    from .seo_source_alignment import check_title_variants_against_primary_subject
    alignment = check_title_variants_against_primary_subject(
        current_title, [title]
    )
    if alignment.missing:
        raise ValueError("SEO_TOPIC_MISMATCH: named subject missing in title")


def _valid_ukrainian_description(description: str) -> bool:
    words = re.findall(r"[а-яёіїєґ]+", description.casefold())
    if not words:
        return False
    ua_letters = sum(c in "іїєґ" for c in description.casefold())
    ru_letters = sum(c in "ыъэё" for c in description.casefold())
    if ua_letters < 4 or (ru_letters > 2 and ru_letters * 3 > ua_letters):
        return False
    ua = {"що", "це", "цей", "цьому", "також", "їх", "його",
          "які", "який", "яка", "людей", "питання", "розмові",
          "учасники", "говорять", "обговорюють", "росіяни", "України".casefold(),
          "про", "через", "свою", "свої", "між", "або", "під",
          "дітей", "після", "війни"}
    ru = {"что", "это", "этот", "этой", "также", "которые",
          "который", "вопросы", "говорят", "обсуждают", "события",
          "между", "происходит", "России".casefold(), "россияне",
          "участники", "тексте", "описано", "говорится", "для",
          "свои", "после", "военных", "действий", "представлены"}
    ua_hits = sum(w in ua for w in words)
    ru_hits = sum(w in ru for w in words)
    return ua_hits >= 3 and ua_hits > ru_hits



def _bilingual_subject_roots(value: str) -> set[str]:
    # Letter normalization permits overlap between closely related Russian
    # and Ukrainian forms without treating channel branding as evidence.
    normalized = (str(value).casefold()
                  .replace("і", "и").replace("ї", "и")
                  .replace("є", "е").replace("ґ", "г"))
    tokens = re.findall(r"[а-яёa-z]{5,}", normalized)
    generic = {
        "росси", "росий", "россий", "украин", "україн", "росиян",
        "россия", "россии", "канала", "канале", "рулетк", "гудбай",
        "сегодня", "расска", "обсужд", "участн", "разгов", "различ",
        "политик", "событи", "ситуац", "видео", "стране",
    }
    aliases = {
        "войн": "war", "війн": "war", "вийн": "war", "виин": "war",
        "налог": "tax", "подат": "tax",
        "бензин": "fuel", "пальн": "fuel", "топлив": "fuel",
        "рыбак": "fishing", "рыбал": "fishing", "рибал": "fishing",
        "джед": "jedi", "фантаз": "fantasy", "фантаст": "fantasy",
        "школ": "school",
        "дрон": "drone", "безпіл": "drone", "беспил": "drone",
        "ракет": "missile",
        "экном": "economy", "эконом": "economy", "економ": "economy",
        "учител": "teacher", "вчител": "teacher",
        "выбор": "election", "вибор": "election",
        "преступ": "crime", "злочин": "crime",
        "обстрел": "attack", "удар": "attack", "атака": "attack",
    }
    roots = set()
    for word in tokens:
        if word[:6] in generic or word in _TOPIC_STOP:
            continue
        root = next((label for stem, label in aliases.items()
                     if word.startswith(stem)), word[:6])
        roots.add(root)
    return roots


def _check_title_description_alignment(title: str, description: str) -> None:
    title_roots = _bilingual_subject_roots(title)
    description_roots = _bilingual_subject_roots(description)
    # Descriptions must actually describe the SEO headline, not another
    # interesting but incidental clip in the same multi-topic transcript.
    if len(title_roots) >= 2 and not title_roots.intersection(description_roots):
        raise ValueError("SEO_TOPIC_MISMATCH: title and description discuss different subjects")



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
    _check_source_video(current_title, source)
    prompt = (
        "Ты редактор YouTube-канала РАША ГУДБАЙ. Верни только JSON: "
        "title, ab_titles (ровно 3), description, tags (8–15), chapters. "
        "ЯЗЫКИ СТРОГО РАЗДЕЛЯЮТСЯ: основной заголовок title и все три "
        "ab_titles ПОЛНОСТЬЮ НА РУССКОМ ЯЗЫКЕ. "
        "Никаких украинских букв і, ї, є, ґ в русских заголовках. "
        "Поле description ПОЛНОСТЬЮ НА УКРАИНСКОМ ЯЗЫКЕ, "
        "без русских предложений, объём 260–4500 символов. "
        "ГЛАВНАЯ ТЕМА УЖЕ УКАЗАНА В ИСХОДНОМ ЗАГОЛОВКЕ. "
        "Сохрани ключевой предмет исходного заголовка в title И в каждом "
        "из трёх вариантов ab_titles, даже если в длинной расшифровке "
        "встречаются случайные разговоры на другие темы. "
        "Не заменяй рыбака и джедая грибами, политика и налоги должны "
        "оставаться политикой и налогами. "
        "Главный заголовок должен называть конкретный центральный сюжет "
        "исходного видео, а не побочную реплику. "
        "Не начинай названия со слов Обсуждение, Диалог, Разговор, Беседа. "
        "Не используй в описании шаблон В тексте описывается. "
        "Не выдумывай факты, цитаты или законодательные изменения. "
        "Бери темы только из расшифровки. "
        "chapters должен быть пустой строкой: проверенных таймкодов нет. "
        "Все результаты только черновики для редакторской проверки. "
        "VIDEO ID: " + video_id + "\nИСХОДНЫЙ ЗАГОЛОВОК: " +
        current_title + "\nРАСШИФРОВКА (фрагменти з початку, середини та кінця):\n" +
        select_source_excerpt(current_title, source, char_budget=23000)
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
    if any(any(ch in "іїєґ" for ch in value.casefold())
           for value in [title, *variants]):
        raise ValueError("Titles must be Russian")
    if re.match(r"^\s*(обсуждение|диалог|разговор|беседа|дискуссия)\b",
                title.casefold()):
        raise ValueError("Generic non-editorial headline")
    _check_editorial_title(current_title, title, source)
    from .seo_source_alignment import check_title_variants_against_primary_subject
    variants_alignment = check_title_variants_against_primary_subject(
        current_title, variants
    )
    if variants_alignment.missing:
        raise ValueError("SEO_TOPIC_MISMATCH: A/B headlines lose named subject")
    for variant in variants:
        roots = _topic_roots(variant)
        if len(roots) >= 3 and not roots.intersection(_topic_roots(source)):
            raise ValueError("SEO_TOPIC_MISMATCH: A/B headline absent from transcript")
    if not 260 <= len(description) <= 4500:
        raise ValueError("Description length invalid")
    if not _valid_ukrainian_description(description):
        raise ValueError("Description must be Ukrainian")
    # Model descriptions must read like a published video description,
    # not like a report about text, podcasts or possible other sources.
    generic_meta = (
        "цей текст є фрагментом", "можливо, з підкаста",
        "у тексті описано", "наданий текст", "можливо, це",
        "у даному тексті", "у вихідному тексті",
    )
    if any(phrase in description.casefold() for phrase in generic_meta):
        raise ValueError("Generic AI meta-description forbidden")
    _check_title_description_alignment(title, description)
    if not isinstance(tags, list) or not 8 <= len(tags) <= 15 or any(
        not isinstance(t, str) or not t.strip() for t in tags
    ):
        raise ValueError("Tags invalid")
    # Remove redundant model tags before checking YouTube's 500-char
    # budget. Eight DISTINCT useful tags are still mandatory.
    normalized_tags: list[str] = []
    seen_tags: set[str] = set()
    for tag in tags:
        clean = tag.strip()
        key = clean.casefold()
        if key not in seen_tags:
            normalized_tags.append(clean)
            seen_tags.add(key)
    if len(normalized_tags) < 8:
        raise ValueError("At least eight unique tags required")
    # At least two tags must be meaningfully connected to the main topic.
    # Channel branding tags are useful, but cannot mask unrelated keywords:
    # e.g., video about Рыбак/Джедай with only military technology tags.
    topic = _topic_roots(title)
    relevant_tags = sum(
        bool(_topic_roots(tag).intersection(topic))
        for tag in normalized_tags
    )
    if topic and relevant_tags < min(2, len(topic)):
        raise ValueError("SEO_TAGS_TOPIC_MISMATCH: no subject-specific tags")
    # YouTube's tag budget counts commas between tags as well as values.
    if len(", ".join(normalized_tags)) > 500:
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
        description=description, tags=tuple(normalized_tags),
        chapters=chapters,
    )
