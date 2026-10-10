"""One-shot offline improvement of a privately staged long-LIVE SEO description.

Reads the owner's existing source and 100%-verified private caption cache.
No YouTube API, new Ollama inference, network access, or video modifications.
Only replace the private manual-review draft when quality warnings decrease.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3

from rg_youtube_control.cached_metadata import cached_public_metadata
from rg_youtube_control.config import app_data_dir
from rg_youtube_control.dialogue_seo import (
    analyze_all_timeline_blocks, preserve_one_grounded_quote, preserve_outline_topics,
)
from rg_youtube_control.free_tools import DEFAULT_OLLAMA_MODEL, load_srt_transcript
from rg_youtube_control.seo_quality_gate import review_seo_package
from rg_youtube_private_ab_repair import _no_missing_block_model
from rg_youtube_real_live_seo_qa import MIN_LONG_LIVE_SECONDS, _captions_span_full_long_live
from rg_youtube_staged_long_live_semantic_qa import DEFAULT_PRIVATE_ROOT

OUTPUT = Path("rg_youtube_private_description_repair_anonymous.json")
URLS = re.compile(r"https?://[^\s<>\"']+")


def grounded_description(old: str, original: str, report: dict) -> str:
    """Draft an exact-topic outline, retaining original URL destinations."""
    topics = []
    seen = set()
    for block in report.get("blocks") or []:
        if block.get("verified") is not True:
            continue
        for item in block.get("topics") or []:
            if not isinstance(item, dict):
                continue
            topic = " ".join(str(item.get("topic") or "").split())
            if topic and topic.casefold() not in seen:
                seen.add(topic.casefold())
                topics.append(topic)
    if not topics:
        return ""
    # YouTube limits descriptions to 5000 Unicode characters, NOT UTF-8 bytes.\n    # First prefer keeping the complete generated description.
    revised, omitted = preserve_outline_topics(old, report, max_body_bytes=20000)
    revised, _ = preserve_one_grounded_quote(revised, report, max_body_bytes=20000)
    urls = list(dict.fromkeys(url.rstrip(".,;!)") for url in URLS.findall(original)))
    missing = [url for url in urls if url not in revised]
    if missing:
        revised += "\n\n" + "\n".join(missing)
    if not omitted and len(revised) <= 5000:
        return revised
    # Fallback is an editorial outline, *not* a claim that 47 topics are one
    # story. Original description and all facts remain separately in the draft.
    intro = "У цьому випуску РАША ГУДБАЙ співрозмовники обговорюють такі теми:"
    result = intro + "\n" + "\n".join("• " + topic for topic in topics)
    result, quote_added = preserve_one_grounded_quote(result, report, max_body_bytes=20000)
    if not quote_added:
        # An existing exact quote may be present, which the quality gate checks.
        pass
    if urls:
        result += "\n\nПосилання з оригінального опису:\n" + "\n".join(urls)
    return result if len(result) <= 5000 else ""


def run(*, root: Path | None = None, db_path: Path | None = None) -> dict:
    out = {
        "schema": "RG_PRIVATE_DESCRIPTION_REPAIR_V1",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "NOT_READY", "youtube_data_api_calls": 0,
        "youtube_modified": False, "nas_modified": False,
        "ollama_called": False, "caption_downloads": 0,
        "source_text_exported": False, "video_ids_exported": False,
        "draft_content_exported": False, "private_draft_updated": False,
        "verified_blocks": 0, "previous_warnings": -1,
        "youtube_description_character_limit": 5000,
        "candidate_warnings": -1, "description_chars": 0,
    }
    private = root or DEFAULT_PRIVATE_ROOT
    db = db_path or app_data_dir() / "rg_youtube_control.db"
    if not db.is_file():
        out["reason"] = "Local metadata database missing"
        return out
    try:
        candidates = sorted(
            (p for p in (private / "private_drafts").glob("*.json")
             if p.is_file() and re.fullmatch(r"[A-Za-z0-9_-]{11}", p.stem)),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
    except OSError:
        candidates = []
    for draft_path in candidates[:5]:
        try:
            video_id = draft_path.stem
            srt = private / "private_source" / (video_id + ".srt")
            if not srt.is_file():
                continue
            with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as conn:
                conn.execute("PRAGMA query_only=ON")
                meta = cached_public_metadata(conn, video_id, "live")
            duration = int(meta.get("duration") or 0)
            if (
                duration < MIN_LONG_LIVE_SECONDS
                or str(meta.get("scheduled_publish_at") or "").strip()
                or str(meta.get("privacy_status") or "public") != "public"
            ):
                continue
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            if (
                draft.get("schema") != "RG_PRIVATE_LONG_LIVE_DRAFT_V1"
                or draft.get("video_id") != video_id
                or not draft.get("review_required")
                or not isinstance(draft.get("package"), dict)
            ):
                continue
            source_description = str(draft.get("source_description") or "")
            if not source_description.strip():
                continue
            captions = load_srt_transcript(srt)
            if not _captions_span_full_long_live(captions, duration):
                continue
            evidence = analyze_all_timeline_blocks(
                captions, model=DEFAULT_OLLAMA_MODEL, chat=_no_missing_block_model,
                cache_dir=private / "private_semantic_cache" / video_id,
                max_chars=5000, max_span_seconds=300,
            )
            if (
                evidence.get("source_integrity_verified") is not True
                or evidence.get("blocks_with_evidence") != evidence.get("blocks_total")
                or evidence.get("cache_hits") != evidence.get("blocks_total")
            ):
                out["reason"] = "Complete verified private cache required"
                return out
            out["verified_blocks"] = int(evidence["blocks_total"])
            package = dict(draft["package"])
            original_description = str(package.get("description") or "")
            if not original_description.strip():
                continue
            def issues(description):
                return review_seo_package(
                    title=str(package.get("title") or ""),
                    description=description,
                    variants=list(package.get("title_variants") or []),
                    evidence_report=evidence,
                    original_description=source_description,
                    original_tags=list(draft.get("source_tags") or []),
                    tags=list(package.get("tags") or []),
                )
            previous = issues(original_description)
            out["previous_warnings"] = len(previous)
            revised = grounded_description(original_description, source_description, evidence)
            if not revised:
                out["status"] = "REVIEW_REQUIRED"
                out["reason"] = "All verified topics, quote and original links do not fit safely"
                return out
            candidate_issues = issues(revised)
            out["candidate_warnings"] = len(candidate_issues)
            out["description_chars"] = len(revised)
            if len(candidate_issues) >= len(previous):
                out["status"] = "REVIEW_REQUIRED"
                out["reason"] = "Offline description did not improve independent quality gate"
                return out
            package["description"] = revised
            draft["package"] = package
            draft["issues"] = candidate_issues
            draft["review_required"] = True
            draft["youtube_modified"] = False
            pending = draft_path.with_suffix(".description-pending")
            pending.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
            pending.replace(draft_path)
            out["private_draft_updated"] = True
            out["status"] = "IMPROVED_REVIEW_DRAFT"
            out["reason"] = "Verified source topics and quotation retained in private review draft"
            return out
        except (OSError, sqlite3.Error, TypeError, ValueError, RuntimeError):
            continue
    out["reason"] = "No matching complete private draft and verified caption cache"
    return out


def main() -> int:
    result = run()
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for key in (
        "status", "verified_blocks", "previous_warnings", "candidate_warnings",
        "description_chars", "private_draft_updated", "reason",
    ):
        print("PRIVATE DESCRIPTION " + key.upper() + ": " + str(result.get(key)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
