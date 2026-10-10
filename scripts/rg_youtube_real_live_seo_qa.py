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

from rg_youtube_control.config import (
    DEFAULT_NAS_TRANSCRIPTS_PATH, app_data_dir, normalize_nas_unc_path,
)
from rg_youtube_control.cached_metadata import cached_public_metadata
from rg_youtube_control.dialogue_seo import (
    analyze_all_timeline_blocks, evidence_outline_text, split_timeline,
)
from rg_youtube_control.free_tools import (
    DEFAULT_OLLAMA_MODEL, fetch_transcript, generate_seo_package_local,
    load_srt_transcript, ollama_chat,
)
from rg_youtube_control.seo_quality_gate import review_seo_package
from rg_youtube_real_seo_local_qa import anonymous_metrics, anonymous_issue_categories

OUTPUT = Path("rg_youtube_real_live_seo_anonymous_qa.json")
MIN_LONG_LIVE_SECONDS = 3 * 60 * 60


def _captions_span_full_long_live(captions: list[dict], duration_seconds: int) -> bool:
    """Fail closed on a short video or an excerpt mistaken for a full LIVE.

    Timestamp span alone is insufficient: 30 isolated caption lines spread
    across three hours are not evidence that the whole stream was transcribed.
    This is a minimum *coverage preflight*, not proof of semantic correctness.
    """
    if duration_seconds < MIN_LONG_LIVE_SECONDS:
        return False
    if len(captions) < max(25, duration_seconds // 60):
        return False
    positions = []
    for row in captions:
        try:
            start = float(row.get("start"))
            if start >= 0 and str(row.get("text") or "").strip():
                positions.append(start)
        except (TypeError, ValueError, OverflowError):
            continue
    if len(positions) < max(25, duration_seconds // 60):
        return False
    if min(positions) > min(600, duration_seconds * 0.1):
        return False
    if max(positions) < duration_seconds * 0.9:
        return False
    if max(positions) > duration_seconds + 600:
        return False
    return True



def run(
    *, max_caption_lookups: int = 8, require_long_live: bool = False,
    preflight_only: bool = False, max_nas_candidates: int = 40,
) -> dict:
    output = {
        "schema": "RG_REAL_LIVE_SEO_LOCAL_QA_V1",
        "status": "NOT_READY",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": "live",
        "mode": ("READ_ONLY_SOURCE_PREFLIGHT_NO_AI" if preflight_only
                 else "READ_ONLY_CAPTIONS_LOCAL_OLLAMA"),
        "caption_lookups": 0,
        "nas_srt_candidates_checked": 0,
        "nas_srt_sources_available": 0,
        "source_ready": False,
        "semantic_quality_verified": False,
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
        try:
            setting = conn.execute(
                "SELECT value FROM settings WHERE key='nas_transcripts_path'"
            ).fetchone()
        except sqlite3.OperationalError:
            setting = None
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
                             list(metadata.get("tags") or []),
                             int(metadata.get("duration") or 0)))
        conn.close()
    except sqlite3.Error:
        output["reason"] = "Read-only LIVE database query failed"
        return output

    output["available_public_archives"] = len(video_rows)
    output["archives_with_cached_original_description"] = len(rows)
    if not rows:
        output["reason"] = "No LIVE archives with a cached original description"
        return output
    # First inspect existing NAS source SRTs. This does not make network or
    # YouTube API calls, and avoids wasting public caption lookups or Ollama.
    raw_nas = str(setting[0] or "").strip() if setting else ""
    nas_root = Path(normalize_nas_unc_path(raw_nas, DEFAULT_NAS_TRANSCRIPTS_PATH))
    selected = None
    try:
        public_budget = max(0, min(int(max_caption_lookups), 8))
        nas_budget = max(1, min(int(max_nas_candidates), 100))
    except (ValueError, TypeError, OverflowError):
        output["reason"] = "Invalid read-only sample size"
        return output
    for video_id, title, source_description, source_tags, duration_seconds in rows[:nas_budget]:
        if require_long_live and duration_seconds < MIN_LONG_LIVE_SECONDS:
            continue
        captions = []
        source_type = ""
        path = nas_root / f"{video_id}.srt"
        output["nas_srt_candidates_checked"] += 1
        try:
            if path.is_file() and 0 < path.stat().st_size <= 40_000_000:
                captions = load_srt_transcript(path)
                if captions:
                    source_type = "nas-srt"
                    output["nas_srt_sources_available"] += 1
        except (OSError, ValueError, RuntimeError, UnicodeError):
            captions = []
        if not captions:
            if output["caption_lookups"] >= public_budget:
                continue
            output["caption_lookups"] += 1
            try:
                captions = fetch_transcript(video_id)
                source_type = "public-captions"
            except (OSError, ValueError, RuntimeError, TimeoutError, TypeError):
                continue
        if not captions or len(captions) < 25:
            continue
        if require_long_live and not _captions_span_full_long_live(
            captions, duration_seconds
        ):
            continue
        try:
            block_count = len(split_timeline(
                captions, max_chars=5000, max_span_seconds=300
            ))
        except (ValueError, TypeError):
            continue
        if (block_count >= 15 if require_long_live else 2 <= block_count <= 14):
            selected = (title, source_description, source_tags, captions)
            output["source_ready"] = True
            output["selected_source_type"] = source_type
            output["selected_timeline_blocks"] = block_count
            break

    if selected is None:
        output["reason"] = (
            "No long LIVE with verified duration and full-span source captions in bounded sample"
            if require_long_live else "No complete moderate-length LIVE sample with source metadata"
        )
        return output
    if preflight_only:
        output["status"] = "SOURCE_READY"
        output["reason"] = "A complete source candidate exists; no Ollama or SEO generation ran"
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
    parser.add_argument("--long-live", action="store_true", help="Require >=3h duration, full-span captions and >=15 timeline blocks")
    parser.add_argument("--preflight-only", action="store_true", help="Check source readiness without calling Ollama")
    parser.add_argument("--caption-probes", type=int, default=None, help="Public caption lookup limit, 0-8")
    args = parser.parse_args()
    caption_probes = args.caption_probes if args.caption_probes is not None else (
        0 if args.preflight_only else 8
    )
    result = run(
        require_long_live=args.long_live,
        preflight_only=args.preflight_only,
        max_caption_lookups=caption_probes,
    )
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
