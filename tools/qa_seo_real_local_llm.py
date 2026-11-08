"""Review-only local LM Studio SEO smoke on an authenticated ALEXPC Runner.

Does not publish, write video metadata, or touch source SRT. Enforces
one loaded managed model at a time before Qwen writer / Gemma critic.
"""
from __future__ import annotations
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from rg_youtube_control.free_tools import DEFAULT_OLLAMA_MODEL, load_srt_transcript
from rg_youtube_control.dialogue_seo import analyze_all_timeline_blocks
from rg_youtube_control.seo_evidence_records import build_evidence_records
from rg_youtube_control.seo_g3_batch_drafts import (
    prepare_source_packet, draft_seo_package, evaluate_independent_draft,
    repair_seo_package, complete_missing_source_variants,
)
from rg_youtube_control.lm_studio_backend import lm_studio_chat

ROOT = Path(r"C:\RG_YT_AGENT_RUNNER\SEO_G1_CHECK\g2_cohort_20261104")
CACHE = ROOT / "g4_end_to_end_10_review_only_20261105" / "evidence_cache"
VID = "Z7AhB4mjvlM"
WRITER = "qwen3-14b"
CRITIC = "google/gemma-4-12b"
API = "http://127.0.0.1:1234"
MANAGED = (WRITER, CRITIC)
LMS_BIN = Path(r"C:\Users\fauto\.lmstudio\bin\lms.exe")
MIN_FREE_GPU_MIB = 8800
# Only instances explicitly loaded by this process may be unloaded.
_OWNED_INSTANCES: set[str] = set()
_PREEXISTING_INSTANCES: set[str] = set()


def _loaded_instance_ids() -> dict[str, list[str]]:
    inventory = _api("/api/v1/models")
    found: dict[str, list[str]] = {}
    for entry in inventory.get("models") or []:
        if not isinstance(entry, dict) or entry.get("key") not in MANAGED:
            continue
        found[entry["key"]] = [
            str(instance["id"]) for instance in entry.get("loaded_instances") or []
            if isinstance(instance, dict) and instance.get("id")
        ]
    return found


def _record_preexisting_instances() -> None:
    """Mark all previously loaded models as belonging to the user."""
    _OWNED_INSTANCES.clear()
    _PREEXISTING_INSTANCES.clear()
    for ids in _loaded_instance_ids().values():
        _PREEXISTING_INSTANCES.update(ids)


def _unload_our_instance(instance_id: str) -> None:
    if instance_id not in _OWNED_INSTANCES:
        return
    _api("/api/v1/models/unload", {"instance_id": instance_id}, timeout=75)
    _OWNED_INSTANCES.discard(instance_id)


def _cleanup_our_models() -> list[str]:
    """Best-effort cleanup after SEO, leaving all preloaded models untouched."""
    errors: list[str] = []
    for instance_id in sorted(_OWNED_INSTANCES.copy()):
        try:
            _unload_our_instance(instance_id)
        except (RuntimeError, ValueError, urllib.error.URLError, TimeoutError, OSError) as exc:
            errors.append(type(exc).__name__ + ":" + instance_id)
    return errors



def _gpu_preflight() -> dict:
    """Refuse to load Qwen while an unrelated job uses RTX 4080 memory."""
    try:
        output = subprocess.run(
            [r"C:\Windows\System32\nvidia-smi.exe",
             "--query-gpu=memory.free,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=8,
        ).stdout.strip().splitlines()
        if not output:
            raise RuntimeError("NVIDIA_GPU_NOT_DETECTED")
        free, total = [int(part.strip()) for part in output[0].split(",")[:2]]
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RuntimeError("GPU_PREFLIGHT_UNAVAILABLE") from exc
    if free < MIN_FREE_GPU_MIB:
        raise RuntimeError(f"GPU_BUSY_FOR_SAFE_LOCAL_SEO free_mib={free}")
    return {"free_mib": free, "total_mib": total}


def _ensure_server() -> bool:
    """Start LM Studio only for this job when the user did not start it."""
    try:
        _api("/api/v1/models", timeout=3)
        return False
    except (urllib.error.URLError, TimeoutError):
        pass
    if not LMS_BIN.is_file():
        raise RuntimeError("LMS_CLI_NOT_INSTALLED")
    try:
        subprocess.run([str(LMS_BIN), "server", "start"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=35)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("LMS_SERVER_START_FAILED") from exc
    for _ in range(12):
        try:
            _api("/api/v1/models", timeout=3)
            return True
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1)
    raise RuntimeError("LMS_SERVER_NOT_READY_AFTER_START")


def _stop_own_server() -> None:
    """Do not stop a server that already belonged to the user."""
    try:
        subprocess.run([str(LMS_BIN), "server", "stop"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


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
    # Only release models loaded in THIS SEO run. Do not touch a user's
    # manually loaded Qwen, Gemma, or models from other applications.
    current = _loaded_instance_ids()
    for key, instance_ids in current.items():
        if key != name:
            for instance_id in instance_ids:
                if instance_id not in _OWNED_INSTANCES:
                    raise RuntimeError("PREEXISTING_MODEL_IN_USE_" + key)
                _unload_our_instance(instance_id)
    current = _loaded_instance_ids()
    if current.get(name):
        return
    result = _api("/api/v1/models/load", {
        "model": name, "context_length": 4096,
        "flash_attention": True, "parallel": 1,
        "offload_kv_cache_to_gpu": False,
    }, timeout=110)
    if result.get("status") != "loaded":
        raise RuntimeError("MODEL_LOAD_NOT_CONFIRMED")
    instance_id = result.get("instance_id") or result.get("model_instance_id")
    if not instance_id:
        current = _loaded_instance_ids()
        new_ids = set(current.get(name) or []) - _PREEXISTING_INSTANCES
        if len(new_ids) != 1:
            raise RuntimeError("MODEL_INSTANCE_OWNERSHIP_UNPROVEN")
        instance_id = next(iter(new_ids))
    instance_id = str(instance_id)
    # Verify the new instance actually exists and was not present before load.
    after = _loaded_instance_ids()
    if (instance_id in _PREEXISTING_INSTANCES
            or instance_id not in (after.get(name) or [])):
        raise RuntimeError("MODEL_INSTANCE_OWNERSHIP_UNPROVEN")
    _OWNED_INSTANCES.add(instance_id)


def _cache_only(*_args: object, **_kwargs: object) -> str:
    raise RuntimeError("UNVERIFIED_CACHE_BLOCK")


def _chat_for(model: str):
    def call(messages: list[dict[str, str]]) -> str:
        print("MODEL_STAGE_START=" + ("writer" if model == WRITER else "critic"), flush=True)
        _model_ready(model)
        reply = lm_studio_chat(
            messages, model=model, timeout=100,
            temperature=0, json_mode=True, num_ctx=4096,
            max_tokens=850 if model == WRITER else 650,
        )
        print("MODEL_STAGE_DONE=" + ("writer" if model == WRITER else "critic"), flush=True)
        return reply
    return call


def main() -> int:
    audit = {"video_id": VID, "publication_allowed": False,
             "human_approved": False, "full_10_video_acceptance": False}
    started = time.monotonic()
    server_started_by_job = False
    try:
        gpu = _gpu_preflight()
        audit["gpu_preflight"] = gpu
        server_started_by_job = _ensure_server()
        audit["server_started_by_job"] = server_started_by_job
        _record_preexisting_instances()
        audit["preexisting_managed_instances_preserved"] = len(_PREEXISTING_INSTANCES)
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
            transcript_rows=cues, max_cards=5)
        audit["source_cards"] = len(source["records"])
        audit["source_provisional"] = source["contains_provisional_sources"]
        draft = draft_seo_package(source=source, chat=_chat_for(WRITER))
        # One missing A/B title can sometimes be recovered deterministically
        # from a timestamped source topic. Never rewrite factual content for it.
        if len(draft["seo"].get("title_variants") or []) == 2:
            try:
                draft = complete_missing_source_variants(source=source, draft=draft)
                audit["source_variant_completion"] = True
                audit["source_variant_requires_recheck"] = True
            except (ValueError, KeyError, TypeError) as variant_error:
                audit["source_variant_completion"] = False
                audit["source_variant_issue"] = str(variant_error)[:120]
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
        # A single constrained repair must address both missing A/B variants
        # and original-source critic flags, followed by a NEW independent check.
        # Do not make the entire smoke fail if only the optional repair fails:
        # the initial source and model-stage evidence remains valuable.
        if draft["status"] != "READY_FOR_INDEPENDENT_AI_REVIEW" or review["issues"]:
            try:
                repaired = repair_seo_package(
                    source=source, previous=draft, critique=review,
                    chat=_chat_for(WRITER),
                )
                second = evaluate_independent_draft(
                    draft=repaired, source=source, chat=_chat_for(CRITIC))
                audit["repair_attempt"] = 1
                audit["repair_format_pass"] = bool(
                    repaired["quality_checks"].get("format_pass"))
                audit["repair_blockers"] = repaired["blockers"]
                audit["repair_ab_count"] = len(
                    repaired["seo"].get("title_variants") or [])
                audit["repair_description_chars"] = len(
                    str(repaired["seo"].get("description") or ""))
                audit["repair_independent_risk"] = second["risk_ai"]
                audit["repair_independent_issues"] = second["issues"]
                audit["repair_unapproved"] = (
                    repaired["publication_allowed"] is False
                    and second["publication_allowed"] is False
                    and not second["human_approved"])
                audit["repair_ai_screened"] = bool(
                    audit["repair_format_pass"]
                    and not second["issues"]
                    and second["risk_ai"] == "low"
                    and audit["repair_unapproved"])
                audit["repair_editorial_approved"] = False
                audit["repair_full_10_video_acceptance"] = False
            except (ValueError, RuntimeError, OSError, TimeoutError) as repair_error:
                audit["repair_issue"] = (
                    type(repair_error).__name__ + ": " + str(repair_error)[:170])
                audit["repair_ai_screened"] = False
                audit["repair_editorial_approved"] = False
    except Exception as exc:
        audit["issue"] = type(exc).__name__
        audit["error_detail"] = str(exc)[:230]
    finally:
        audit["model_cleanup_errors"] = _cleanup_our_models()
        audit["seo_owned_models_remaining"] = len(_OWNED_INSTANCES)
        audit["preexisting_models_were_unloaded"] = False
        if server_started_by_job:
            try:
                # Do not stop a server that another app started using meanwhile.
                all_inventory = _api("/api/v1/models")
                any_models_loaded = any(
                    isinstance(x, dict) and bool(x.get("loaded_instances"))
                    for x in all_inventory.get("models") or []
                )
                if not any_models_loaded and not _OWNED_INSTANCES:
                    _stop_own_server()
                    audit["seo_owned_server_stopped"] = True
                else:
                    audit["seo_owned_server_stopped"] = False
                    audit["server_preserved_for_other_models"] = True
            except (OSError, RuntimeError, ValueError, urllib.error.URLError,
                    TimeoutError) as stop_exc:
                audit["server_stop_skipped"] = type(stop_exc).__name__
    audit["elapsed_seconds"] = round(time.monotonic() - started, 1)
    print("RG_SEO_LIVE_LLM_AUDIT=" + json.dumps(audit, ensure_ascii=False))
    if audit.get("independent_ai_risk") is None:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
