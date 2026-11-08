"""G7 evidence-attached Ukrainian SEO claims; manual publication gate always on.

Model proposes concise Ukrainian assertions with explicit quote IDs.
Independent validation checks each assertion against the supporting literal
speech (names/numbers and topic overlap). This establishes attribution, not truth.
"""
from __future__ import annotations
import json
import re
from typing import Any, Callable

from .seo_content_editor import grounded_description_issue, _words

def _distinct_references(report: dict[str, Any], limit: int = 20) -> list[dict[str, str]]:
    references=[]
    seen=set()
    for block in report.get("blocks") or []:
        if not isinstance(block,dict) or block.get("verified") is False:
            continue
        for topic in block.get("topics") or []:
            if not isinstance(topic,dict):
                continue
            quote=" ".join(str(topic.get("evidence") or "").split())
            if not (30<=len(quote)<=250) or quote.casefold() in seen:
                continue
            seen.add(quote.casefold())
            references.append({"id":f"q{len(references)+1}","time":str(block.get("start_stamp") or ""),
                "quote":quote})
            if len(references)>=limit:
                return references
    return references


def _validate_claim(claim: dict[str,Any], source: dict[str,str]) -> str:
    statement=" ".join(str(claim.get("text") or "").split())
    if not (35<=len(statement)<=210):
        return "CLAIM_LENGTH"
    if "«" in statement or "»" in statement:
        return "COPY_PASTED_QUOTE"
    if re.search(r"[ыэъё]",statement.casefold()) or re.search(
        r"(?i)\b(?:говорит|что|почему|потому|из-за|который|также|вот)\b",
        statement,
    ):
        return "MIXED_RUSSIAN"
    if not re.search(r"[іїєґ]",statement.casefold()):
        return "NOT_UKRAINIAN"
    if not re.search(r"(?i)\b(?:співрозмовник|учасник|ведучий|гість|росіянин|росіянка|за словами|на думку)\b",statement):
        return "CLAIM_NOT_ATTRIBUTED"
    quote=source["quote"]
    nums=set(re.findall(r"\b\d{2,}(?:[.,]\d+)?\b",statement))
    if nums-set(re.findall(r"\b\d{2,}(?:[.,]\d+)?\b",quote)):
        return "UNSUPPORTED_CLAIM_NUMBER"
    # Named entities can be transliterated, so only accept ones that are
    # recognizable by both cross-language 5-character normalized stems.
    source_words=_words(quote)
    for word in re.findall(r"\b[А-ЯІЇЄҐ][а-яіїєґ]{4,}\b",statement):
        if word in {"Співрозмовник","Співрозмовниця","Учасник","Учасниця","Ведучий",
                    "Гість","Росіянин","Росіянка","Україна","Росія","України",
                    "Росії","Далі","Також","Водночас","Після","Підчас"}:
            continue
        if not (_words(word) & source_words):
            return "UNSUPPORTED_NAMED_ENTITY"
    # Require a close lexical entailment across languages, not just two
    # coincidentally shared generic topic words. Some valid paraphrases will
    # be held for review; fabricated facts must never gain a false PASS.
    attributed = {
        "співр", "учасн", "ведуч", "говор", "пояс", "вваж",
        "відпо", "запит", "зазна", "розпо", "кажет", "згаду",
        "відмі", "диску", "росія", "украї", "відео",
    }
    core = {part for part in _words(statement) if part not in attributed}
    overlap = core & source_words
    if len(overlap) < 2:
        return "NOT_SOURCE_SPECIFIC"
    novel = core - source_words
    if len(novel) > max(1, len(core) // 4):
        return "CLAIM_ADDS_UNCORROBORATED_SUBJECTS"
    return ""


def generate_attributed_claim_description(
    *,report:dict[str,Any],current_title:str,model:str,
    chat:Callable[...,str],timeout:float=85,
) -> tuple[str,str,dict[str,Any]]:
    """Separate source extraction, Ukrainian writing and per-claim verification.

    Never automatically approve a generated claim or a YouTube metadata write.
    """
    refs=_distinct_references(report)
    details={"source_count":len(refs),"accepted_claims":0,
             "sources_used":[],"publication_allowed":False}
    if len(refs)<3:
        return "","INSUFFICIENT_DISTINCT_SOURCE_QUOTES",details
    source_by_id={r["id"]:r for r in refs}
    messages=[
        {"role":"system","content":"Ти редактор українського YouTube. Поверни ВИКЛЮЧНО JSON. Усі твердження — тільки як слова учасників, а не доведені факти."},
        {"role":"user","content":json.dumps({
            "task":"Напиши 3–4 конкретні УКРАЇНСЬКІ речення, кожне про ІНШУ цитату. Відповідь тільки JSON: {\"claims\":[{\"quote_id\":\"q1\",\"text\":\"Співрозмовник ...\"}]}. "
                   "Кожне речення 70–170 символів; спирайся ТІЛЬКИ на прив'язану цитату, "
                   "зберігай думки й запитання як позицію співрозмовника. "
                   "Не копіюй російські репліки, переклади зміст українською. "
                   "Без вступів, шаблонів, чисел, імен або нових мотивів, "
                   "непідтверджених цитатою. Не вигадуй відсутні події. "
                   "Не повторюй одну тему тричі.",
            "title_is_metadata_not_factual_evidence":current_title,
            "source_quotes":refs
        },ensure_ascii=False)}
    ]
    try:
        raw=chat(messages,model=model,timeout=timeout,temperature=0.05,json_mode=True,num_ctx=16384)
        data=json.loads(str(raw or "").strip())
        claims=data.get("claims")
        if not isinstance(claims,list) or not 3<=len(claims)<=4:
            return "","INVALID_CLAIM_COUNT",details
        valid=[]
        used=set()
        for item in claims:
            if not isinstance(item,dict):
                return "","INVALID_CLAIM",details
            quote_id=str(item.get("quote_id") or "")
            if quote_id not in source_by_id or quote_id in used:
                return "","MISSING_OR_DUPLICATED_QUOTE_ID",details
            issue=_validate_claim(item,source_by_id[quote_id])
            if issue:
                return "",issue,details
            used.add(quote_id)
            valid.append(" ".join(str(item["text"]).split()))
        joined=" ".join(x.rstrip(".!?")+"." for x in valid)
        issue=grounded_description_issue(joined,report)
        if issue:
            return "",issue,details
        details.update({"accepted_claims":len(valid),"sources_used":sorted(used)})
        return joined,"",details
    except (ValueError,TypeError,RuntimeError,TimeoutError,KeyError) as exc:
        return "",type(exc).__name__,details