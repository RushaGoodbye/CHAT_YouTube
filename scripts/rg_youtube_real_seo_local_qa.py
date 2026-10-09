"""Run ONE entire existing NAS transcript through Ollama, without publishing.

This is a read-only semantic QA pilot on the user's Windows machine.
Video IDs, titles, transcripts, generated titles, descriptions, quotes and
tags are NEVER logged, exported or included in the GitHub artifact.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

from rg_youtube_control.config import (
    DEFAULT_NAS_TRANSCRIPTS_PATH, app_data_dir, normalize_nas_unc_path,
)
from rg_youtube_control.dialogue_seo import (
    analyze_all_timeline_blocks, evidence_outline_text, split_timeline,
)
from rg_youtube_control.free_tools import (
    DEFAULT_OLLAMA_MODEL, generate_seo_package_local,
    load_srt_transcript, ollama_chat,
)
from rg_youtube_control.seo_quality_gate import review_seo_package

OUTPUT = Path("rg_youtube_real_seo_anonymous_qa.json")


def anonymous_metrics(report: dict, package: dict | None = None) -> dict:
    """Return only non-identifying counts and boolean checks."""
    blocks = int(report.get("blocks_total") or 0)
    verified = int(report.get("blocks_with_evidence") or 0)
    result = {
        "timeline_blocks": blocks,
        "grounded_blocks": verified,
        "source_integrity_verified": report.get("source_integrity_verified") is True,
        "source_rows": int(report.get("source_rows_with_text") or 0),
        "semantic_coverage_complete": bool(blocks and blocks == verified),
    }
    if package is not None:
        choices = list(package.get("title_variants") or [])
        result.update({
            "ab_titles_count": len(choices),
            "ab_titles_distinct": len({str(x).strip().casefold() for x in choices}) == 3,
            "description_characters": len(str(package.get("description") or "")),
            "tags_count": len(package.get("tags") or []),
            "prompt_topics_not_sent": int(package.get("timeline_prompt_omitted_count") or 0),
            "model_warnings_count": len(package.get("ab_quality_issues") or []),
        })
    return result


def run() -> dict:
    output = {
        "schema": "RG_REAL_SEO_LOCAL_QA_V1",
        "status": "NOT_READY",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": "main",
        "mode": "READ_ONLY_LOCAL_AI_ZERO_YOUTUBE_API",
        "source_text_exported": False,
        "generated_content_exported": False,
        "youtube_published": False,
        "manual_review_required": True,
    }
    db = app_data_dir() / "rg_youtube_control.db"
    if not db.is_file():
        output["reason"] = "Local synchronized video metadata not found"
        return output
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=ON")
        videos = conn.execute(
            "SELECT video_id, title FROM videos WHERE profile='main' "
            "AND scheduled_publish_at IS NULL"
        ).fetchall()
        setting = conn.execute(
            "SELECT value FROM settings WHERE key='nas_transcripts_path'"
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        output["reason"] = "Local database unavailable in read-only mode"
        return output
    raw = str(setting[0] or "").strip() if setting else ""
    root = Path(normalize_nas_unc_path(raw, DEFAULT_NAS_TRANSCRIPTS_PATH))
    if not root.is_dir():
        output["reason"] = "NAS transcript directory unavailable"
        return output

    # Never copy the transcript. Only inspect candidates known to the main
    # channel; bound the pilot by whole-video timeline blocks, not by clipping.
    selected = None
    for video_id, title in videos:
        if not title or not isinstance(video_id, str) or len(video_id) != 11:
            continue
        path = root / f"{video_id}.srt"
        try:
            if not path.is_file() or path.stat().st_size > 15_000_000:
                continue
            captions = load_srt_transcript(path)
            if len(captions) < 25:
                continue
            count = len(split_timeline(captions))
            if 3 <= count <= 16:
                selected = (title, captions)
                break
        except (OSError, ValueError):
            continue
    if selected is None:
        output["reason"] = "No full-length NAS SRT within 3-16 timeline blocks"
        return output

    title, rows = selected
    try:
        evidence = analyze_all_timeline_blocks(
            rows, model=DEFAULT_OLLAMA_MODEL, chat=ollama_chat,
            max_chars=5000, max_span_seconds=300, timeout=120,
        )
        output.update(anonymous_metrics(evidence))
        if not evidence["source_integrity_verified"]:
            output["status"] = "REVIEW_REQUIRED"
            output["reason"] = "SRT coverage integrity did not pass"
            return output
        if not evidence["blocks_with_evidence"]:
            output["status"] = "REVIEW_REQUIRED"
            output["reason"] = "Ollama found no source-verifiable topics"
            return output
        package = generate_seo_package_local(
            current_title=title,
            current_description="",
            current_tags=[],
            transcript=evidence_outline_text(evidence),
            evidence_report=evidence,
            model=DEFAULT_OLLAMA_MODEL,
            timeout=120,
        )
        output.update(anonymous_metrics(evidence, package))
        issues = review_seo_package(
            title=package.get("title") or "",
            description=package.get("description") or "",
            variants=package.get("title_variants") or [],
            evidence_report=evidence,
        )
        output["semantic_gate_warnings_count"] = len(issues)
        output["status"] = "STRUCTURE_PASS" if not issues else "REVIEW_REQUIRED"
        output["reason"] = (
            "All structural gates passed; human content review still required"
            if not issues else "Generated package needs manual semantic review"
        )
        return output
    except Exception:
        # Never leak a title, video ID, transcript or model output via
        # exception text into public GitHub logs.
        output["status"] = "REVIEW_REQUIRED"
        output["reason"] = "Local semantic model or SEO generation could not complete"
        return output


def main() -> int:
    report = run()
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("REAL VIDEO SEO QA STATUS:", report["status"], flush=True)
    print("SEMANTICALLY VERIFIED BLOCKS:",
          report.get("grounded_blocks", 0), "/", report.get("timeline_blocks", 0), flush=True)
    print("A/B TITLES:", report.get("ab_titles_count", 0), flush=True)
    print("SEO WARNINGS:", report.get("semantic_gate_warnings_count", -1), flush=True)
    print("REASON:", report.get("reason", "No additional reason"), flush=True)
    # A REVIEW_REQUIRED result is an honest QA finding, not a tooling crash.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
