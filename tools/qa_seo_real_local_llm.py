"""Review-only local LM Studio SEO smoke on an authenticated ALEXPC Runner.

Does not publish, write video metadata, or touch source SRT. Enforces
one loaded managed model at a time before Qwen writer / Gemma critic.
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
from pathlib import Path

from rg_youtube_control.free_tools import DEFAULT_OLLAMA_MODEL, load_srt_transcript
from rg_youtube_control.dialogue_seo import analyze_all_timeline_blocks
from rg_youtube_control.seo_evidence_records import build_evidence_records
from rg_youtube_control.seo_g3_batch_drafts import (
    prepare_source_packet, draft_seo_package, evaluate_independent_draft,
)
from rg_youtube_control.lm_studio_backend import lm_studio_chat

ROOT = Path(r"C:\RG_YT_AGENT_RUNNER\SEO_G1_CHECK\g2_cohort_20261104")
CACHE = ROOT / "g4_end_to_end_10_review_only_20261105" / "evidence_cache"
VID = "Z7AhB4mjvlM"
WRITER = "qwen3-14b"
CRITIC = "google/gemma-4-12b"
API = "http://127.0.0.1:1234"
MANAGED = (WRITER, CRITIC)


def _api(path: str, payload: dict | None = None, timeout: float = 20) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API + path, data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="GET" if payload is None else "POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("INVALID_LOCAL_MODEL_SERVER_REPLY")
    return result


def _model_ready(name: str) -> None:
    inventory = _api("/api/v1/models")
    models = inventory.get("models") or []
    for entry in models:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if key in MANAGED and key != name:
            for instance in entry.get("loaded_instances") or []:
                if isinstance(instance, dict) and instance.get("id"):
                    _api("/api/v1/models/unload",
                         {"instance_id": instance["id"]}, timeout=75)
    inventory = _api("/api/v1/models")
    for entry in inventory.get("models") or []:
        if entry.get("key") == name and entry.get("loaded_instances"):
            return
    result = _api("/api/v1/models/load", {
        "model": name, "context_length": 4096,
        "flash_attention": True, "parallel": 1,
        "offload_kv_cache_to_gpu": False,
    }, timeout=110)
    if result.get("status") != "loaded":
        raise RuntimeError("MODEL_LOAD_NOT_CONFIRMED")


def _cache_only(*_args: object, **_kwargs: object) -> str:
    raise RuntimeError("UNVERIFIED_CACHE_BLOCK")


def _chat_for(model: str):
    def call(messages: list[dict[str, str]]) -> str:
        _model_ready(model)
        return lm_studio_chat(messages, model=model, timeout=110,
                              temperature=0, json_mode=True, num_ctx=4096)
    return call


def main() -> int:
    audit = {"video_id": VID, "publication_allowed": False,
             "human_approved": False, "full_10_video_acceptance": False}
    started = time.monotonic()
    try:
        file = ROOT / "source_captions" / (VID + ".srt")
        if not file.is_file() or not CACHE.is_dir():
            raise RuntimeError("ORIGINAL_SOURCE_OR_CACHE_MISSING")
        cues = load_srt_transcript(file)
        report = analyze_all_timeline_blocks(
            cues, model=DEFAULT_OLLAMA_MODEL, chat=_cache_only, cache_dir=CACHE)
        proof = build_evidence_records(
            video_id=VID, timeline_report=report, transcript_rows=cues)
        if not proof["complete_literal_source_coverage"]:
            raise RuntimeError("ORIGINAL_SRT_LITERAL_COVERAGE_INCOMPLETE")
        first = (proof.get("evidence_records") or [None])[0]
        if first is None:
            raise RuntimeError("NO_QUOTED_SOURCE_CARD")
        card = {"video_id": VID, "record_id": 1, "start_s": first["start_s"],
                "status": "PROVISIONAL_SOURCE_REVIEW",
                "source_quote": first["verbatim_quote"],
                "source_context": first["verbatim_quote"],
                "candidate_topic": first["topic"],
                "publication_allowed": False}
        source = prepare_source_packet(
            video_id=VID, cards=[card], expanded_evidence=proof,
            transcript_rows=cues)
        audit["source_cards"] = len(source["records"])
        audit["source_provisional"] = source["contains_provisional_sources"]
        draft = draft_seo_package(source=source, chat=_chat_for(WRITER))
        audit["format_pass"] = bool(draft["quality_checks"].get("format_pass"))
        audit["blockers"] = draft["blockers"]
        audit["title_chars"] = len(str(draft["seo"].get("title") or ""))
        audit["ab_count"] = len(draft["seo"].get("title_variants") or [])
        audit["description_chars"] = len(str(draft["seo"].get("description") or ""))
        audit["tag_count"] = len(draft["seo"].get("tags") or [])
        review = evaluate_independent_draft(
            draft=draft, source=source, chat=_chat_for(CRITIC))
        audit["independent_ai_risk"] = review["risk_ai"]
        audit["independent_issues"] = review["issues"]
        audit["editorial_review_required"] = review["editorial_review_required"]
        audit["unapproved"] = (
            review["publication_allowed"] is False
            and draft["publication_allowed"] is False
            and review["human_approved"] is False)
    except Exception as exc:
        audit["issue"] = type(exc).__name__
        audit["error_detail"] = str(exc)[:230]
    audit["elapsed_seconds"] = round(time.monotonic() - started, 1)
    print("RG_SEO_LIVE_LLM_AUDIT=" + json.dumps(audit, ensure_ascii=False))
    if audit.get("independent_ai_risk") is None:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
