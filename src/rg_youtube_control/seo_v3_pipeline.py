"""Universal SEO v3: source-typed claim ledger BEFORE any SEO writing.

Separate preview-only pipeline. Never calls YouTube, never publishes, and
never silently upgrades a spoken opinion to an independently proven fact.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .seo_v2_pipeline import (
    _ask, _extract, _proof_index, _select_topics, _source_numbers,
    _draft_numbers, validate_draft,
)
from .seo_v2_evidence import parse_srt
from .seo_v3_entities import unsupported_names_v3 as unsupported_names
from .seo_v3_claims import build_claim_ledger, check_claim_type_constraints, expand_literal_coverage
from .seo_v3_fields import compose_claim_fields

Chat = Callable[[str], dict[str, Any]]


def _write_from_claims(
    ledger: dict[str, Any],
    topics: list[dict[str, Any]],
    chat: Chat,
) -> dict[str, Any]:
    claims = ledger["claims"]
    permitted_ids = {entry["claim_id"] for entry in claims}
    instruction = (
        "You write Ukrainian YouTube SEO from a SOURCE-TYPED CLAIM LEDGER, "
        "not directly from raw subtitles or an earlier AI-generated story. "
        "The source type is mandatory: QUESTION describes a question, "
        "CONDITIONAL describes an if/then possibility, HYPOTHESIS is a "
        "speaker's suggestion, SPEAKER_STATEMENT describes only what "
        "the person said, NOT external verified fact. "
        "NO ledger entry has external verification. NEVER claim that "
        "investigation proved the truth, that a real cause is known, "
        "or that a hypothetical outcome happened. "
        "Do not guess any proper name that is unclear in the original "
        "transcription. Prefer a neutral role or topic over a garbled name. "
        "One primary Ukrainian title and 3 DISTINCT A/B questions or "
        "supported angles; title max 100 chars. "
        "Description: 400-900 chars of attributable factual reporting "
        "about what participants DISCUSS (not about unproven outcomes). "
        "8-15 useful topical tags ONLY when explicitly grounded by "
        "the quote. If the material cannot support 8 tags or 400 chars, "
        "return fewer/shorter; the draft will be blocked for review. "
        "Return JSON ONLY with: title (string), "
        "variant_evidence (exactly 3 objects {text, evidence_ids}), "
        "description (string), tag_evidence (list of objects "
        "{tag, evidence_ids}), support_ids ({title: list of IDs, "
        "description: list of IDs}). Source ID must be from claim_id "
        "and never invented. Citation links must be semantically correct, "
        "not arbitrary. The language of metadata is Ukrainian. "
        "Topic labels are orientation only, NOT sources of facts.\n"
        "TOPIC ORDER:\n"
        + json.dumps(topics, ensure_ascii=False)
        + "\nSOURCE-TYPED CLAIM LEDGER:\n"
        + json.dumps(claims, ensure_ascii=False)
    )
    reply = _ask(chat, instruction)
    support = reply.get("support_ids")
    if not isinstance(support, dict):
        support = {}
    for key, text_key in (("title_variants", "text"), ("tags", "tag")):
        key_in = "variant_evidence" if key == "title_variants" else "tag_evidence"
        raw = reply.get(key_in)
        if not isinstance(raw, list):
            # Legacy output is not trusted: invalid citations are detected
            # by validation rather than fabricated as a convenient fallback.
            continue
        if key == "title_variants":
            raw = raw[:3]
        else:
            raw = raw[:15]
        rows = [
            row for row in raw
            if isinstance(row, dict) and str(row.get(text_key) or "").strip()
        ]
        reply[key] = [str(row[text_key]).strip() for row in rows]
        support[key] = [
            [str(eid) for eid in row.get("evidence_ids") or []
             if isinstance(eid, str) and eid in permitted_ids]
            for row in rows
        ]
    reply["support_ids"] = support
    return reply


def audit_draft_against_claims(
    draft: dict[str, Any],
    claims: dict[str, Any],
    reviewer: Chat,
) -> dict[str, Any]:
    """Ask the independent critic to audit modality per sentence/field.

    A malformed, over-broad or unstructured reviewer response fails closed.
    A citation only proves the sentence was uttered, NOT the factual truth.
    """
    # The independent auditor checks cited claims, not an unrelated
    # transcript-length ledger. Exclude uncited material to keep the local
    # RTX 4080 inference bounded and reduce false associations.
    supports = draft.get("support_ids") or {}
    cited: set[str] = set()
    for field in ("title", "description", "title_variants", "tags"):
        groups = supports.get(field) or []
        if field in ("title", "description"):
            cited.update(str(eid) for eid in groups if isinstance(eid, str))
        else:
            for group in groups:
                if isinstance(group, list):
                    cited.update(str(eid) for eid in group if isinstance(eid, str))
    cited_claims = [
        claim for claim in claims["claims"]
        if str(claim.get("claim_id")) in cited
    ]
    prompt = (
        "You are a skeptical, INDEPENDENT Ukrainian SEO source auditor. "
        "Audit EACH title and A/B headline, EACH description sentence, "
        "and EACH tag against the source-typed claims. "
        "Every issue MUST name field and reason. "
        "A QUESTION does not establish an answer or real cause. "
        "A CONDITIONAL does not establish the consequent occurred. "
        "A HYPOTHESIS is only an attributed opinion. "
        "A SPEAKER_STATEMENT confirms words spoken, not objective truth. "
        "Reject garbled proper names, false causal connections, fabricated "
        "events, invented motives, certainty from speculation, and "
        "misleading assertion of verified analysis. "
        "CRITICAL CALIBRATION: A truthful QUESTION such as 'Чи було "
        "звільнення покаранням?' does NOT assert that punishment happened. "
        "An accurate topic tag such as 'питання про корупцію' does NOT "
        "assert that corruption occurred. A sentence 'Співрозмовник "
        "припускає зв'язок' attributes speculation and does not prove it. "
        "Do NOT reject any of these merely because the evidence is a "
        "QUESTION, CONDITIONAL, or SPEAKER_STATEMENT. "
        "Reject ONLY a verifiable semantic defect: an invented named "
        "person, event or number, a fabricated link between unrelated "
        "quotations, a false presupposition within the words, or a "
        "speaker's opinion converted into asserted objective fact. "
        "Do not claim that an interrogative 'establishes no answer' as "
        "the sole reason to reject a genuine question; that is its point. "
        "A negative finding must quote EXACT offending draft text and "
        "the actual evidence_id, then explain the specific factual "
        "contradiction or missing evidence. "
        "Return exactly JSON {\"issues\":[{\"field\":"
        "\"title|title_variants|description|tags\","
        "\"reason\":\"specific unsupported text and claim_id\"}]}. "
        "If all fields are supported return an empty issues array. "
        "Do not approve publication.\nDRAFT:\n"
        + json.dumps(draft, ensure_ascii=False)
        + "\nSOURCE-TYPED CLAIMS:\n"
        + json.dumps(cited_claims, ensure_ascii=False)
    )
    try:
        result = _ask(reviewer, prompt)
    except (ValueError, RuntimeError, TypeError, TimeoutError):
        result = {}
    issues = result.get("issues")
    if not isinstance(issues, list) or any(
        not isinstance(issue, dict)
        or str(issue.get("field") or "") not in {
            "title", "title_variants", "description", "tags",
        }
        or not str(issue.get("reason") or "").strip()
        for issue in issues
    ):
        return {
            "review_status": "FAILED_CLOSED",
            "issues": [{
                "field": "reviewer",
                "reason": "INVALID_CLAIM_AUDIT_SCHEMA",
            }],
        }
    return {"issues": issues, "review_status": "SOURCE_AUDITED"}


def generate_claim_first_seo(
    srt: str,
    chat: Chat,
    independent_review: Chat | None = None,
) -> dict[str, Any]:
    """Preview: classify quotes, then draft and independently validate.

    No retries that reintroduce model-generated fictional connections.
    Every rejection stays in the report; publication is never allowed.
    """
    cues = parse_srt(srt)
    # Literal evidence needs no generative call: avoid slow extraction
    # retries and retain verified, whole-timeline SRT quotations.
    from .seo_v3_claims import literal_evidence_from_cues
    evidence, windows = literal_evidence_from_cues(cues)
    evidence = expand_literal_coverage(cues, evidence)
    # One local lexical pass selects *source snippets*, not invented facts.
    # Avoid a separate Gemma topic request which previously exhausted its
    # 45s budget and left the title call queued behind inference.
    from .seo_v3_claims import select_source_topics_without_llm
    topics = select_source_topics_without_llm(evidence)
    topic_selection_degraded = not bool(topics)
    proof = _proof_index(evidence, topics)
    # Name spelling is checked against the entire literal transcript, not
    # just the short excerpt selected for generation. This does not create
    # new citations or authorize any invented statement.
    name_proof = [*proof, *({"quote": cue.text} for cue in cues)]
    claim_ledger = build_claim_ledger(proof)
    if not claim_ledger["claims"]:
        return {
            "pipeline": "RG_SEO_CLAIM_FIRST_V3",
            "status": "INSUFFICIENT_VERIFIED_EVIDENCE",
            "draft": None,
            "evidence": evidence,
            "claims": claim_ledger,
            "windows": windows,
            "topics": topics,
            "publication_allowed": False,
            "editorial_approved": False,
        }
    visible = {row["claim_id"] for row in claim_ledger["claims"]}
    visible_topics = [
        {**topic, "evidence_ids": [
            i for i in topic["evidence_ids"] if i in visible
        ]}
        for topic in topics
    ]
    draft = compose_claim_fields(claim_ledger, visible_topics, chat)
    # Source-only, deterministic removal of COMPLETE sentences containing
    # unsupported names. Apply only when ≥400 cited characters survive;
    # the full revised draft still needs independent semantic review.
    from .seo_v3_entities import prune_unverified_description_sentences
    draft, name_sentence_pruned_count = prune_unverified_description_sentences(
        draft, name_proof, claim_ledger,
    )
    gate = validate_draft(draft, evidence, cues, allowed_ids=visible)
    modality_issues = check_claim_type_constraints(draft, claim_ledger)
    if modality_issues:
        gate["issues"] = sorted(set([
            *gate["issues"], "CLAIM_MODALITY_UNSUPPORTED",
        ]))
    names = unsupported_names(draft, name_proof)
    if names:
        gate["issues"] = sorted(set([
            *gate["issues"], "UNVERIFIED_NAMED_ENTITIES",
        ]))
        gate["unverified_names"] = names
    # External information cannot be invented from a question. Treat all
    # spoken statements as attributed statements, never proven journalism.
    extra_numbers = sorted(_draft_numbers(draft) - _source_numbers(cues))
    review = None
    if independent_review is not None:
        try:
            review = audit_draft_against_claims(
                draft, claim_ledger, independent_review,
            )
        except (ValueError, RuntimeError, TypeError, TimeoutError):
            review = {
                "review_status": "FAILED_CLOSED",
                "issues": [{
                    "field": "reviewer",
                    "reason": "INDEPENDENT_REVIEW_UNAVAILABLE",
                }],
            }
    repair_diagnostics: dict[str, str] = {}
    if (review is not None and independent_review is not None):
        from .seo_v3_repair import repair_claim_fields
        def recheck(candidate: dict[str, Any]) -> dict[str, Any]:
            result = validate_draft(candidate, evidence, cues, allowed_ids=visible)
            if unsupported_names(candidate, name_proof):
                result["issues"] = sorted(set([
                    *result["issues"], "UNVERIFIED_NAMED_ENTITIES",
                ]))
            if check_claim_type_constraints(candidate, claim_ledger):
                result["issues"] = sorted(set([
                    *result["issues"], "CLAIM_MODALITY_UNSUPPORTED",
                ]))
            from .seo_v3_numbers import check_cited_numbers
            if check_cited_numbers(candidate, claim_ledger):
                result["issues"] = sorted(set([
                    *result["issues"], "NUMERIC_PROVENANCE_UNSUPPORTED",
                ]))
            return result

        draft, gate, review, repair_diagnostics = repair_claim_fields(
            draft, claim_ledger, name_proof, review, chat,
            lambda candidate: audit_draft_against_claims(
                candidate, claim_ledger, independent_review,
            ),
            recheck,
        )
        modality_issues = check_claim_type_constraints(draft, claim_ledger)
        names = unsupported_names(draft, name_proof)
        extra_numbers = sorted(_draft_numbers(draft) - _source_numbers(cues))
        # Rebuild the final gate from the FINAL draft after all repairs.
        # A previous candidate's global flags must not block a safe revision.
        gate = recheck(draft)
        # The editor may have corrected a description but left a different
        # unsourced proper name. Retry the lossless, whole-sentence filter
        # on the final candidate, never replace a name with guessed text.
        # A changed draft needs a NEW independent audit of ALL SEO fields.
        cleaned, removed_after_repair = prune_unverified_description_sentences(
            draft, name_proof, claim_ledger,
        )
        if removed_after_repair:
            cleaned_gate = recheck(cleaned)
            if not cleaned_gate.get("issues"):
                try:
                    cleaned_review = audit_draft_against_claims(
                        cleaned, claim_ledger, independent_review,
                    )
                except (ValueError, RuntimeError, TypeError, TimeoutError):
                    cleaned_review = {"review_status": "FAILED_CLOSED",
                                      "issues": [{"field": "reviewer",
                                                  "reason": "UNAVAILABLE"}]}
                if (cleaned_review.get("review_status") == "SOURCE_AUDITED"
                        and not cleaned_review.get("issues")):
                    draft, gate, review = cleaned, cleaned_gate, cleaned_review
                    name_sentence_pruned_count += removed_after_repair
                    modality_issues = check_claim_type_constraints(draft, claim_ledger)
                    names = unsupported_names(draft, name_proof)
                    extra_numbers = sorted(_draft_numbers(draft) - _source_numbers(cues))
    # Numeric evidence must belong to the exact quotes cited by each
    # output field, not merely appear somewhere in an unrelated SRT cue.
    from .seo_v3_numbers import check_cited_numbers
    numeric_provenance_issues = check_cited_numbers(draft, claim_ledger)
    if numeric_provenance_issues:
        gate["issues"] = sorted(set([
            *gate["issues"], "NUMERIC_PROVENANCE_UNSUPPORTED",
        ]))
        gate["numeric_provenance_issues"] = numeric_provenance_issues
    # Every sentence in the final (possibly repaired) description must
    # still have its own immutable claim citation. A field-level ID list
    # alone is insufficient to validate a rewritten description.
    from .seo_v3_fields import check_sentence_provenance
    provenance_issues = check_sentence_provenance(draft, claim_ledger)
    if provenance_issues:
        gate["issues"] = sorted(set([
            *gate["issues"], "SENTENCE_PROVENANCE_INVALID",
        ]))
        gate["sentence_provenance_issues"] = provenance_issues
    status = "READY_FOR_HUMAN_REVIEW"
    if (gate["issues"] or modality_issues or names or extra_numbers
            or topic_selection_degraded
            or review is None
            or review.get("review_status") != "SOURCE_AUDITED"
            or review.get("issues")):
        status = "REVIEW_REQUIRED"
    return {
        "pipeline": "RG_SEO_CLAIM_FIRST_V3",
        "status": status,
        "draft": {
            key: draft.get(key)
            for key in ("title", "title_variants", "description", "tags",
                        "support_ids")
        },
        "gate": gate,
        "claims": claim_ledger,
        "modality_issues": modality_issues,
        "repair_diagnostics": repair_diagnostics,
        "name_sentence_pruned_count": name_sentence_pruned_count,
        "sentence_provenance": draft.get("sentence_provenance") or [],
        "unverified_names": names,
        "independent_review": review,
        "topics": topics,
        "topic_selection_degraded": topic_selection_degraded,
        "evidence": evidence,
        "windows": windows,
        "writer_evidence_quotes": len(proof),
        "full_evidence_quotes": len(evidence["accepted"]),
        "publication_allowed": False,
        "editorial_approved": False,
    }
