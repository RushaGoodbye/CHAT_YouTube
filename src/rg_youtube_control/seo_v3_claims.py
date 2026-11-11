"""Universal SEO v3: immutable, source-typed claim ledger.

Source type is determined from VERBATIM words, never a model's paraphrase.
A statement spoken in a video is NOT an independently established fact.
No channel-specific people, events, or keywords are embedded here.
"""
from __future__ import annotations

import re
from typing import Any

QUESTION_START = re.compile(
    r"^\s*(?:а\s+)?(?:чому|чем|чому|хто|кто|що|что|як|как|коли|когда|"
    r"навіщо|зачем|чий|чья|який|яка|яке|какой|какова|каков|какие|чи|ли|невже|разве|скільки|сколько|"
    r"де|где|откуда|звідки|почему)\b", re.IGNORECASE,
)
CONDITIONAL = re.compile(
    r"(?<!\w)(?:якщо|если|якби|если\s+бы|коли\s+б|в\s+случае|"
    r"за\s+умови|за\s+условия|як\s+би)(?!\w)", re.IGNORECASE,
)
HYPOTHESIS = re.compile(
    r"(?<!\w)(?:можливо|возможно|может\s+быть|може\s+бути|"
    r"ймовірно|вероятно|припускаю|предполагаю|на\s+мою\s+думку|"
    r"по\s+моему\s+мнению|я\s+думаю|я\s+считаю|"
    r"міг\s+би|мог\s+бы|могло\s+бы)(?!\w)", re.IGNORECASE,
)
# Captions can merge introductions and questions without punctuation.
# Recognize relatively unambiguous interrogatives inside those captions.
EMBEDDED_QUESTION = re.compile(
    r"(?<!\w)(?:какова|каковы|почему|зачем|навіщо|чому|"
    r"скільки|сколько|хто|кто)(?!\w)", re.IGNORECASE,
)
GENERIC_ANALYSIS = re.compile(
    r"(?i)(?:аналіз\s+(?:доводить|свідчить|показує)|"
    r"доведен[оі]|встановлен[оі]\s+(?:причин|факт)|"
    r"(?:справжн(?:я|і|ої|ю)|реальн(?:а|і|ої|у))\s+причин(?:а|и|у|ою)?|"
    r"доказано|анализ\s+показал)"
)

KINDS = {"QUESTION", "CONDITIONAL", "HYPOTHESIS", "SPEAKER_STATEMENT"}


def classify_statement(quote: str) -> str:
    """Use explicit surface cues; default is speaker claim, never verified fact."""
    value = str(quote or "").strip()
    if "?" in value or QUESTION_START.search(value) or EMBEDDED_QUESTION.search(value):
        return "QUESTION"
    if CONDITIONAL.search(value):
        return "CONDITIONAL"
    if HYPOTHESIS.search(value):
        return "HYPOTHESIS"
    return "SPEAKER_STATEMENT"


def build_claim_ledger(proof: list[dict[str, Any]]) -> dict[str, Any]:
    claims = []
    for evidence in proof:
        quote = str(evidence.get("quote") or "").strip()
        evidence_id = str(evidence.get("evidence_id") or "")
        if not quote or not evidence_id:
            continue
        claims.append({
            "claim_id": evidence_id,
            "source_type": classify_statement(quote),
            "source_quote": quote,
            "source_evidence_ids": [evidence_id],
            "start_ms": evidence.get("start_ms"),
            "end_ms": evidence.get("end_ms"),
            "verified_external_fact": False,
        })
    return {
        "schema": "RG_SEO_SOURCE_CLAIMS_V3",
        "claims": claims,
        "review_required": True,
        "publication_allowed": False,
    }


def expand_literal_coverage(
    cues: list[Any], ledger: dict[str, Any], *, per_window: int = 5,
) -> dict[str, Any]:
    """Improve source coverage independent of any video's subject.

    Sample different parts of EACH SRT window, verify every exact quote
    against the original cues, and keep source-only selection metadata.
    Never accept a model-written paraphrase as evidence.
    """
    from .seo_v2_evidence import evidence_ledger, make_windows
    from .seo_v2_pipeline import _fallback_window_quotes

    windows = make_windows(cues)
    existing = list(ledger.get("accepted") or [])
    proposed = [{
        "quote": str(row["quote"]),
        "cue_indices": list(row["cue_indices"]),
    } for row in existing]
    for indices in windows:
        proposed.extend(
            _fallback_window_quotes(cues, indices, max_quotes=per_window)
        )
    validated = evidence_ledger(cues, proposed)
    # Preserve rejected model proposals separately from source samples.
    validated["rejected"] = [
        *(ledger.get("rejected") or []), *validated.get("rejected", []),
    ]
    validated["source_cues"] = len(cues)
    validated["analysis_windows_total"] = len(windows)
    covered = {
        i for item in validated["accepted"]
        for i in item["cue_indices"]
    }
    validated["windows_without_quotes"] = [
        n for n, indices in enumerate(windows)
        if not any(i in covered for i in indices)
    ]
    validated["source_cues_with_evidence"] = len(covered)
    validated["deterministic_source_expansion"] = max(
        0, len(validated["accepted"]) - len(existing)
    )
    validated["review_required"] = bool(
        validated["rejected"]
        or validated["windows_without_quotes"]
        or not validated["accepted"]
    )
    validated["publication_allowed"] = False
    return validated


def check_claim_type_constraints(
    draft: dict[str, Any], ledger: dict[str, Any],
) -> list[dict[str, str]]:
    """Conservative lexical guard; human/editor review remains mandatory.

    This cannot prove semantic entailment; it only catches some unsafe
    rewrites, leaving all uncertain statements for the model reviewer.
    """
    by_id = {c["claim_id"]: c for c in ledger["claims"]}
    support = draft.get("support_ids") or {}
    findings: list[dict[str, str]] = []
    entries = [
        ("title", str(draft.get("title") or ""), support.get("title") or []),
        ("description", str(draft.get("description") or ""), support.get("description") or []),
    ]
    for field in ("title_variants", "tags"):
        texts = draft.get(field) or []
        groups = support.get(field) or []
        for i, value in enumerate(texts):
            cited = groups[i] if isinstance(groups, list) and i < len(groups) else []
            entries.append((field, str(value), cited))
    for field, value, cited in entries:
        ids = cited if isinstance(cited, list) else []
        source_kinds = {by_id[i]["source_type"] for i in ids if i in by_id}
        # A SPEAKER_STATEMENT is not external verification either. Unless a
        # separate independent source is supplied (not supported in this
        # preview), no source type licenses claims of proven analysis.
        if source_kinds and GENERIC_ANALYSIS.search(value):
            findings.append({
                "field": field,
                "reason": "UNVERIFIED_OBJECTIVE_CERTAINTY",
            })
        if not ids or any(i not in by_id for i in ids):
            findings.append({"field": field, "reason": "CLAIM_SOURCE_ID_MISSING"})
    return findings
