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
INQUIRY_PARTICLES = re.compile(
    r"(?:\?|(?<!\w)(?:чи|ли|разве|невже)(?!\w))", re.IGNORECASE,
)
GENERIC_ANALYSIS = re.compile(
    r"(?i)(?:аналіз\s+(?:доводить|свідчить|показує)|"
    r"доведен[оі]|встановлен[оі]\s+(?:причин|факт)|"
    r"справжн[іья]\s+причин|реальн[іья]\s+причин|"
    r"доказано|анализ\s+показал)"
)

KINDS = {"QUESTION", "CONDITIONAL", "HYPOTHESIS", "SPEAKER_STATEMENT"}


def classify_statement(quote: str) -> str:
    """Use explicit surface cues; default is speaker claim, never verified fact."""
    value = str(quote or "").strip()
    if "?" in value or QUESTION_START.search(value):
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
        if source_kinds & {"QUESTION", "CONDITIONAL", "HYPOTHESIS"}:
            if GENERIC_ANALYSIS.search(value):
                findings.append({
                    "field": field,
                    "reason": "UNSUPPORTED_CERTAINTY_FROM_UNCERTAIN_SOURCE",
                })
        if not ids or any(i not in by_id for i in ids):
            findings.append({"field": field, "reason": "CLAIM_SOURCE_ID_MISSING"})
    return findings
