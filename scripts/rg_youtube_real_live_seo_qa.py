"""Private, read-only LIVE-channel genuine SEO pilot using public captions.

Never writes video data or AI-generated content into the job workspace.
Only numeric counters and coarse categorical diagnostics leave ALEXPC.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import argparse
from pathlib import Path
import sqlite3

from rg_youtube_control.config import app_data_dir
from rg_youtube_control.cached_metadata import cached_public_metadata
from rg_youtube_control.dialogue_seo import (
    analyze_all_timeline_blocks, evidence_outline_text, split_timeline,
)
from rg_youtube_control.free_tools import (
    DEFAULT_OLLAMA_MODEL, fetch_transcript, generate_seo_package_local, ollama_chat,
)
from rg_youtube_control.seo_quality_gate import review_seo_package
from rg_youtube_real_seo_local_qa import anonymous_metrics, anonymous_issue_categories

OUTPUT = Path("rg_youtube_real_live_seo_anonymous_qa.json")


def run(*, max_caption_lookups: int = 8, require_long_live: bool = False) -> dict:
    output = {
        "schema": "RG_REAL_LIVE_SEO_LOCAL_QA_V1",
        "status": "NOT_READY",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": "live",
        "mode": "READ_ONLY_PUBLIC_CAPTIONS_LOCAL_OLLAMA",
        "caption_lookups": 0,
        "source_text_exported": False,
        "generated_content_exported": False,
        "youtube_data_api_calls": 0,
        "youtube_modified": False,
        "manual_review_required": True,
        "length_profile": "long" if require_long_live else "moderate",
    }
    db = app_data_dir() / "rg_youtube_control.db"
    if not db.is_file():
        output["reason"] = "Local LIVE archive metadata database missing"
        return output

    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=ON")
        video_rows = conn.execute(
            """SELECT video_id, title FROM videos WHERE profile='live'
               AND scheduled_publish_at IS NULL
               AND COALESCE(privacy_status, 'public')='public'
               ORDER BY video_id DESC"""
        ).fetchall()
        rows = []
        for video_id, title in video_rows:
            if not title or not isinstance(video_id, str) or len(video_id) != 11:
                continue
            # The videos table has no description/tags. Reuse the same
            # source-only cache as the Windows SEO generator; NEVER confuse
            # generated draft metadata with the original YouTube metadata.
            metadata = cached_public_metadata(conn, video_id, "live")
            if metadata.get("source_description_available"):
                rows.append((video_id, title, str(metadata["description"]),
                             list(metadata.get("tags") or [])))
        conn.close()
    except sqlite3.Error:
        output["reason"] = "Read-only LIVE database query failed"
        return output

    output["available_public_archives"] = len(video_rows)
    output["archives_with_cached_original_description"] = len(rows)
    if not rows:
        output["reason"] = "No LIVE archives with a cached original description"
        return output
    selected = None
    for video_id, title, source_description, source_tags in rows:
        if output["caption_lookups"] >= max(1, min(int(max_caption_lookups), 8)):
            break
        if not title or not isinstance(video_id, str) or len(video_id) != 11:
            continue
        output["caption_lookups"] += 1
        try:
            captions = fetch_transcript(video_id)
            if not captions or len(captions) < 25:
                continue
            block_count = len(split_timeline(captions, max_chars=5000, max_span_seconds=300))
            if (block_count >= 15 if require_long_live else 2 <= block_count <= 14):
                selected = (title, source_description, source_tags, captions)
                break
        except (OSError, ValueError, RuntimeError, TimeoutError, TypeError):
            continue

    if selected is None:
        output["reason"] = (
            "No fully-captioned long LIVE archive in bounded sample"
            if require_long_live else "No fully-captioned moderate-length LIVE archive in bounded sample"
        )
        return output

    title, source_description, source_tags, captions = selected
    try:
        evidence = analyze_all_timeline_blocks(
            captions, model=DEFAULT_OLLAMA_MODEL, chat=ollama_chat,
            max_chars=5000, max_span_seconds=300, timeout=120,
        )
        output.update(anonymous_metrics(evidence))
        if not evidence["source_integrity_verified"] or not evidence["blocks_with_evidence"]:
            output["status"] = "REVIEW_REQUIRED"
            output["reason"] = "LIVE source integrity or grounded topic coverage incomplete"
            return output

        package = generate_seo_package_local(
            current_title=title,
            current_description=source_description,
            current_tags=source_tags,
            transcript=evidence_outline_text(evidence),
            evidence_report=evidence,
            model=DEFAULT_OLLAMA_MODEL, timeout=120,
        )
        output.update(anonymous_metrics(evidence, package))
        issues = review_seo_package(
            title=package.get("title") or "",
            description=package.get("description") or "",
            variants=package.get("title_variants") or [],
            evidence_report=evidence,
            original_description=source_description,
            original_tags=source_tags,
            tags=package.get("tags") or [],
        )
        output["semantic_gate_warnings_count"] = len(issues)
        output["semantic_gate_warning_categories"] = anonymous_issue_categories(issues)
        output["status"] = "STRUCTURE_PASS" if not issues else "REVIEW_REQUIRED"
        output["reason"] = (
            "LIVE structure passed; human semantic review still required"
            if not issues else "LIVE SEO requires manual semantic review"
        )
    except Exception:
        output["status"] = "REVIEW_REQUIRED"
        output["reason"] = "Local LIVE semantic model or package generation did not complete"
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Private read-only LIVE SEO QA")
    parser.add_argument("--long-live", action="store_true", help="Require at least 15 timeline blocks")
    args = parser.parse_args()
    result = run(require_long_live=args.long_live)
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("REAL LIVE SEO:", result["status"], flush=True)
    print("LIVE CANDIDATES TRIED:", result["caption_lookups"], flush=True)
    print("VERIFIED BLOCKS:", result.get("grounded_blocks", 0), "/", result.get("timeline_blocks", 0), flush=True)
    print("A/B TITLES:", result.get("ab_titles_count", 0), flush=True)
    print("SEO WARNINGS:", result.get("semantic_gate_warnings_count", -1), flush=True)
    print("WARNING CATEGORIES:", ",".join(result.get("semantic_gate_warning_categories") or []), flush=True)
    print("REASON:", result.get("reason", ""), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
