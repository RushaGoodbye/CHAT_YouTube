"""Read-only acceptance of 10 local SRT sources on an authorized GitHub Runner.

No LLM inference, file modification, YouTube API or automatic publication.
This is source-coverage QA, NOT full SEO editorial acceptance.
"""
from __future__ import annotations
import json
import sys
from collections import Counter
from pathlib import Path

from rg_youtube_control.free_tools import DEFAULT_OLLAMA_MODEL, load_srt_transcript
from rg_youtube_control.dialogue_seo import analyze_all_timeline_blocks
from rg_youtube_control.seo_evidence_records import build_evidence_records
from rg_youtube_control.seo_g3_batch_drafts import prepare_source_packet

BASE = Path(r"C:\RG_YT_AGENT_RUNNER\SEO_G1_CHECK\g2_cohort_20261104")
SOURCE = BASE / "source_captions"
CACHE = BASE / "g4_end_to_end_10_review_only_20261105" / "evidence_cache"
IDS = (
    "ovDuKFGKEXo", "Z7AhB4mjvlM", "tptN1zRv2hs", "PnLR5O0EWYM",
    "H-z5A9WoeTY", "DywWeHtnuhM", "cMw5_kJipzA", "AVl_yO8pXIU",
    "MF8txEoPwjg", "QCIuLwQm4nU",
)


def cache_only_chat(*_args: object, **_kwargs: object) -> str:
    """Forbid generation; do not rewrite source or create missing evidence."""
    raise RuntimeError("UNCACHED_SOURCE_NEEDS_REVIEW")


def run() -> int:
    if not SOURCE.is_dir() or not CACHE.is_dir():
        print("BLOCKED: source SRT directory or verified evidence cache unavailable")
        return 2
    output = []
    for video_id in IDS:
        item: dict[str, object] = {
            "video_id": video_id,
            "source_ready": False,
            "publication_allowed": False,
            "editorial_approved": False,
        }
        file = SOURCE / (video_id + ".srt")
        if not file.is_file():
            item["issue"] = "MISSING_ORIGINAL_SRT"
            output.append(item)
            continue
        try:
            cues = load_srt_transcript(file)
            report = analyze_all_timeline_blocks(
                cues, model=DEFAULT_OLLAMA_MODEL, chat=cache_only_chat,
                cache_dir=CACHE,
            )
            proof = build_evidence_records(
                video_id=video_id, timeline_report=report, transcript_rows=cues
            )
            item["captions"] = len(cues)
            item["blocks_total"] = len(report.get("blocks") or [])
            item["blocks_verified"] = sum(
                b.get("verified") is True for b in report.get("blocks") or []
            )
            item["source_candidates"] = len(proof["source_cue_candidates"])
            item["candidate_windows"] = len(proof["source_cue_candidate_windows"])
            item["missing_model_quote_blocks"] = proof["blocks_without_grounded_quotes"]
            item["nonsemantic_terminal_blocks"] = proof["nonsemantic_caption_blocks"]
            item["unverified_timeline_blocks"] = [
                int(b["index"]) for b in report.get("blocks") or []
                if b.get("verified") is not True and b.get("index") is not None
            ]
            item["rejected_quote_reasons"] = dict(Counter(
                x.get("reason", "UNKNOWN") for x in proof.get("rejected_evidence") or []
            ))
            item["selected_cue_block_ids"] = proof["source_cue_candidate_windows"]
            item["literal_srt_blocks_missing"] = proof["blocks_without_literal_srt_cues"]
            item["literal_srt_coverage_complete"] = bool(
                proof["complete_literal_source_coverage"]
            )
            item["provisional_unverified_cues"] = len(
                proof["source_cue_provisional_unverified_ids"]
            )
            item["complete_evidence_coverage"] = bool(
                proof["complete_evidence_coverage"]
            )
            item["source_cue_complete_timeline_verified"] = bool(
                proof["source_cue_complete_timeline_verified"]
            )
            item["source_ready"] = bool(
                proof["complete_evidence_coverage"]
                and proof["complete_literal_source_coverage"]
                and proof["source_cue_complete_timeline_verified"]
                and len(proof["source_cue_candidates"]) >= 3
            )
            if not item["source_ready"]:
                item["issue"] = "MODEL_TOPIC_QA_BLOCKED"
            # Build a source packet for a REVIEW-ONLY SEO draft from original
            # SRT. It must be blocked from publishing even if all cues exist.
            first = (proof.get("evidence_records") or [None])[0]
            if first is not None:
                literal = first["verbatim_quote"]
                topic = first["topic"]
                start = first["start_s"]
            else:
                candidates = proof["source_cue_candidates"]
                if not candidates:
                    raise ValueError("NO_ORIGINAL_SOURCE_QUOTES")
                literal = candidates[0]["source_quote"]
                topic = "Дослівна репліка, тема потребує редакторської перевірки"
                start = candidates[0]["start_s"]
            cards = [{
                "video_id": video_id,
                "record_id": 1,
                "start_s": start,
                "status": "PROVISIONAL_SOURCE_REVIEW",
                "source_quote": literal,
                "source_context": literal,
                "candidate_topic": topic,
                "publication_allowed": False,
            }]
            packet = prepare_source_packet(
                video_id=video_id, cards=cards, expanded_evidence=proof,
                transcript_rows=cues, max_cards=12,
            )
            item["source_packet_ready"] = bool(
                packet["records"] and
                packet["contains_provisional_sources"] and
                packet["source_material_requires_editorial_review"] and
                packet["publication_allowed"] is False
            )
            item["source_packet_records"] = len(packet["records"])
            item["source_packet_literal_only"] = packet["expanded_literal_only"]
            item["source_packet_time_span"] = [
                packet["records"][0]["start_s"],
                packet["records"][-1]["start_s"],
            ]
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
            item["issue"] = "SOURCE_QA_EXCEPTION_" + type(exc).__name__
        output.append(item)

    summary = {
        "schema": "RG_SEO_REAL_10_SOURCE_READONLY_QA_V1",
        "total": len(IDS),
        "source_ready": sum(row["source_ready"] is True for row in output),
        "literal_srt_ready": sum(
            row.get("literal_srt_coverage_complete") is True for row in output
        ),
        "source_packets_ready_for_editorial_draft": sum(
            row.get("source_packet_ready") is True for row in output
        ),
        "source_qa_failed_ids": [
            row["video_id"] for row in output
            if row.get("literal_srt_coverage_complete") is not True
            or row.get("source_packet_ready") is not True
        ],
        "model_topic_incomplete_ids": [
            row["video_id"] for row in output if row.get("source_ready") is not True
        ],
        "approved_seo_packages": 0,
        "full_seo_acceptance_performed": False,
        "publication_allowed": False,
        "items": output,
    }
    print("RG_SEO_READONLY_COHORT=" + json.dumps(summary, ensure_ascii=False))
    if (summary["literal_srt_ready"] != len(IDS)
            or summary["source_packets_ready_for_editorial_draft"] != len(IDS)):
        print("FAIL: 10/10 original SRT or provisional source packets not proven")
        return 1
    print("PASS: 10/10 original SRT sources and review-only G3 packets; "
          "independent SEO language/semantic acceptance is NOT done")
    return 0


if __name__ == "__main__":
    sys.exit(run())
