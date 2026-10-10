"""One real full-span 3h+ LIVE semantic SEO QA on private ALEXPC staging.

- Reads one owner video metadata record (1 YouTube Data API read).
- Reads a previously staged private SRT (no media download).
- Analyzes every timeline block locally with Ollama qwen3:8b.
- Resumes interrupted work using private F: evidence cache.
- Saves a review-only SEO draft locally, NEVER posts to YouTube.
- Exports ONLY numeric anonymous checks to GitHub Actions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
from typing import Callable

from rg_youtube_control.cached_metadata import cached_public_metadata
from rg_youtube_control.config import PROFILE_TARGETS, app_data_dir
from rg_youtube_control.dialogue_seo import (
    analyze_all_timeline_blocks, evidence_outline_text, split_timeline,
)
from rg_youtube_control.free_tools import (
    DEFAULT_OLLAMA_MODEL, generate_seo_package_local, load_srt_transcript,
    ollama_chat,
)
from rg_youtube_control.seo_quality_gate import review_seo_package
from rg_youtube_control.service import quota_budget_status, record_quota_units
from rg_youtube_control.youtube_api import YouTubeClient
from rg_youtube_real_live_seo_qa import (
    MIN_LONG_LIVE_SECONDS, _captions_span_full_long_live,
)
from rg_youtube_real_seo_local_qa import (
    anonymous_issue_categories, anonymous_metrics,
)

OUTPUT = Path("rg_youtube_staged_long_live_semantic_anonymous.json")
DEFAULT_PRIVATE_ROOT = Path("F:/RG_YOUTUBE_CONTROL_QA")
MAX_SRT_BYTES = 15_000_000


def _safe_gpu_available() -> bool:
    """Never begin GPU-intensive QA while the ALEXPC GPU is clearly busy."""
    try:
        p = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=7,
        )
        raw = p.stdout.strip().splitlines()[0]
        util, memory = [int(item.strip()) for item in raw.split(",")[:2]]
        return util < 65 and memory < 11000
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        # Runner may be provisioned without nvidia-smi in PATH; Ollama itself
        # remains responsible for GPU availability.
        return True


def _foreign_gpu_compute_active() -> bool:
    """Find a different heavy CUDA workload without flagging Ollama itself.

    Overall GPU utilization is HIGH during legitimate Ollama inference, so
    using it as an in-flight stop signal cancels our own analysis every
    fifth block. Instead inspect distinct CUDA processes, exclude the
    local Ollama model runtime, and stop only for a foreign heavy client.
    """
    try:
        probe = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=process_name,used_gpu_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=7,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    for row in probe.stdout.splitlines():
        try:
            process, memory = row.rsplit(",", 1)
            normalized = process.strip().casefold().replace("\\", "/")
            name = normalized.rsplit("/", 1)[-1]
            if any(word in name for word in ("ollama", "llama-server", "llama_server")):
                continue
            if int(memory.strip()) >= 1024:
                return True
        except (ValueError, IndexError):
            continue
    return False


def run(
    *, db_path: Path | None = None,
    private_root: Path | None = None,
    client_factory: Callable = YouTubeClient,
    chat: Callable = ollama_chat,
    gpu_check: Callable = _safe_gpu_available,
    foreign_gpu_check: Callable = _foreign_gpu_compute_active,
) -> dict:
    out = {
        "schema": "RG_STAGED_LONG_LIVE_SEMANTIC_QA_V1",
        "status": "NOT_READY",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": "live", "length_profile": "long",
        "mode": "OWNER_SOURCE_PRIVATE_SRT_LOCAL_OLLAMA",
        "youtube_modified": False,
        "nas_modified": False,
        "source_text_exported": False,
        "video_ids_exported": False,
        "draft_content_exported": False,
        "credentials_exported": False,
        "manual_review_required": True,
        "youtube_data_api_calls": 0,
        "caption_downloads": 0,
        "ollama_called": False,
        "private_draft_saved": False,
        "private_evidence_cache_enabled": False,
        "source_caption_rows": 0,
        "timeline_blocks": 0,
        "grounded_blocks": 0,
        "ab_titles_count": 0,
        "semantic_gate_warnings_count": -1,
    }
    started = time.monotonic()
    db = db_path or app_data_dir() / "rg_youtube_control.db"
    root = private_root or DEFAULT_PRIVATE_ROOT
    source_root = root / "private_source"
    try:
        if not db.is_file() or not source_root.is_dir():
            out["reason"] = "Private long-LIVE source or local video DB missing"
            return out
        # The private folder is NOT a GitHub workspace or uploaded artifact.
        entries = [
            item for item in source_root.glob("*.srt")
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", item.stem)
            and item.is_file() and 0 < item.stat().st_size <= MAX_SRT_BYTES
        ]
        if not entries:
            out["reason"] = "No staged private full-length SRT"
            return out
        with sqlite3.connect(str(db)) as conn:
            conn.row_factory = sqlite3.Row
            candidates = []
            for item in entries:
                meta = cached_public_metadata(conn, item.stem, "live")
                if (int(meta.get("duration") or 0) >= MIN_LONG_LIVE_SECONDS
                    and not str(meta.get("scheduled_publish_at") or "").strip()
                    and str(meta.get("privacy_status") or "public") == "public"):
                    candidates.append((int(meta["duration"]), item, meta))
            if not candidates:
                out["reason"] = "No staged source matched a public completed LIVE"
                return out
            candidates.sort(key=lambda x: x[0], reverse=True)
            duration, srt_file, cached = candidates[0]
            captions = load_srt_transcript(srt_file)
            out["source_caption_rows"] = len(captions)
            if not _captions_span_full_long_live(captions, duration):
                out["reason"] = "Staged SRT no longer spans the verified long LIVE"
                return out
            blocks = split_timeline(
                captions, max_chars=5000, max_span_seconds=300,
            )
            out["timeline_blocks"] = len(blocks)
            if len(blocks) < 15:
                out["reason"] = "Too few full source blocks for long LIVE QA"
                return out
            if not gpu_check():
                out["status"] = "GPU_BUSY"
                out["reason"] = "GPU is active; semantic QA skipped to protect stream runtime"
                return out
            budget = quota_budget_status(conn)
            if budget["exhausted"] or int(budget["spendable"]) < 1:
                out["reason"] = "Read-only owner metadata blocked by quota reserve"
                return out
            client = client_factory(profile="live")
            client.credentials()
            items, n = client.video_details_with_request_count([srt_file.stem])
            count = int(n)
            if count != 1:
                out["reason"] = "Unexpected number of owner metadata API reads"
                return out
            record_quota_units(conn, count, purpose="video")
            out["youtube_data_api_calls"] = count
            matching = [
                row for row in (items or [])
                if str(row.get("id") or "") == srt_file.stem
            ]
            if len(matching) != 1:
                out["reason"] = "Owner metadata did not match staged video"
                return out
            snippet = dict(matching[0].get("snippet") or {})
            channel = str(cached.get("channel_id") or PROFILE_TARGETS["live"])
            if str(snippet.get("channelId") or "") != channel:
                out["reason"] = "Owner metadata is from another channel"
                return out
            source_description = str(snippet.get("description") or "").strip()
            if not source_description:
                out["reason"] = "Owner original description is missing"
                return out
            source_tags = [
                str(x).strip() for x in snippet.get("tags") or []
                if str(x).strip()
            ]
            title = str(cached.get("title") or snippet.get("title") or "").strip()
            if not title:
                out["reason"] = "Original title missing"
                return out

        cache = root / "private_semantic_cache" / srt_file.stem
        cache.mkdir(parents=True, exist_ok=True)
        out["private_evidence_cache_enabled"] = True
        total = len(blocks)
        def progress(message: str) -> None:
            match = re.search(r"(\d+)/(\d+)", message)
            if match:
                done = int(match.group(1))
                if done == 1 or done % 5 == 0 or done == total:
                    print(f"LONG LIVE PROGRESS: {done}/{total}", flush=True)
                # Do not check total utilization while Ollama runs:
                # its *own* inference would trip that signal. A competing
                # CUDA process is the only safe in-flight stop criterion.
                if done > 1 and done % 5 == 0 and foreign_gpu_check():
                    raise RuntimeError("GPU_BUSY_DURING_SEMANTIC_QA")

        try:
            out["ollama_called"] = True
            evidence = analyze_all_timeline_blocks(
                captions,
                model=DEFAULT_OLLAMA_MODEL, chat=chat,
                cache_dir=cache, progress=progress,
                max_chars=5000, max_span_seconds=300, timeout=120,
            )
            out.update(anonymous_metrics(evidence))
            out["verified_cache_hits"] = int(evidence.get("cache_hits") or 0)
            out["remaining_unverified_blocks"] = len(evidence.get("unverified_blocks") or [])
            if (
                evidence.get("source_integrity_verified") is not True
                or int(evidence.get("blocks_analyzed") or 0) != total
                or not evidence.get("blocks_with_evidence")
            ):
                out["status"] = "REVIEW_REQUIRED"
                out["reason"] = "Full source evidence incomplete"
                return out
            package = generate_seo_package_local(
                current_title=title,
                current_description=source_description,
                current_tags=source_tags,
                transcript=evidence_outline_text(evidence),
                evidence_report=evidence,
                model=DEFAULT_OLLAMA_MODEL, timeout=120,
            )
            out.update(anonymous_metrics(evidence, package))
            out["ab_generation_gate_issues_count"] = len(
                package.get("ab_quality_issues") or []
            )
            issues = review_seo_package(
                title=package.get("title") or "",
                description=package.get("description") or "",
                variants=package.get("title_variants") or [],
                evidence_report=evidence,
                original_description=source_description,
                original_tags=source_tags,
                tags=package.get("tags") or [],
            )
            out["semantic_gate_warnings_count"] = len(issues)
            out["semantic_gate_warning_categories"] = (
                anonymous_issue_categories(issues)
            )
            out["status"] = "STRUCTURE_PASS" if not issues else "REVIEW_REQUIRED"
            out["reason"] = (
                "Full long LIVE analyzed; review-only SEO draft saved"
                if not issues else "Long LIVE analyzed; quality warnings need review"
            )
            draft = {
                "schema": "RG_PRIVATE_LONG_LIVE_DRAFT_V1",
                "video_id": srt_file.stem,
                "model": DEFAULT_OLLAMA_MODEL,
                "source_title": title,
                "source_description": source_description,
                "source_tags": source_tags,
                "package": package,
                "issues": issues,
                "review_required": True,
                "youtube_modified": False,
            }
            draft_root = root / "private_drafts"
            draft_root.mkdir(parents=True, exist_ok=True)
            tmp = draft_root / (srt_file.stem + ".pending")
            tmp.write_text(json.dumps(draft, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(draft_root / (srt_file.stem + ".json"))
            out["private_draft_saved"] = True
        except Exception as exc:
            out["status"] = (
                "GPU_BUSY" if str(exc) == "GPU_BUSY_DURING_SEMANTIC_QA"
                else "REVIEW_REQUIRED"
            )
            out["reason"] = (
                "GPU became busy; evidence cache retained for continuation"
                if out["status"] == "GPU_BUSY"
                else "Private local semantic analysis or SEO package failed"
            )
    except Exception:
        out["status"] = "NOT_READY"
        out["reason"] = "Local source or owner metadata could not be verified"
    finally:
        out["elapsed_seconds"] = round(time.monotonic() - started)
    return out


def main() -> int:
    result = run()
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for key in (
        "status", "source_caption_rows", "timeline_blocks",
        "grounded_blocks", "ab_titles_count", "semantic_gate_warnings_count",
        "private_draft_saved", "youtube_data_api_calls", "elapsed_seconds",
        "reason",
    ):
        print("LONG LIVE REAL QA " + key.upper() + ":", result.get(key),
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
