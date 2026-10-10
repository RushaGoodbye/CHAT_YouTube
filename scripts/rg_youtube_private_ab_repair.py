"""One-shot private A/B title repair using the existing verified long LIVE evidence.

No fresh caption download, no YouTube Data API, no source or draft export.
One bounded Ollama title-only generation. Reuses verified private cache on F:.
A replacement is accepted only when exactly 3 source-grounded titles strictly
reduce existing SEO gate warnings. All SEO drafts remain manual-review-only.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Callable

from rg_youtube_control.cached_metadata import cached_public_metadata
from rg_youtube_control.config import app_data_dir
from rg_youtube_control.dialogue_seo import (
    ab_title_issues, analyze_all_timeline_blocks, complete_grounded_ab_variants,
    evidence_outline_text,
)
from rg_youtube_control.free_tools import (
    DEFAULT_OLLAMA_MODEL, _recover_title_variants, load_srt_transcript,
)
from rg_youtube_control.seo_quality_gate import review_seo_package
from rg_youtube_real_live_seo_qa import (
    MIN_LONG_LIVE_SECONDS, _captions_span_full_long_live,
)
from rg_youtube_staged_long_live_semantic_qa import DEFAULT_PRIVATE_ROOT

OUTPUT = Path("rg_youtube_private_ab_repair_anonymous.json")


def choose_verified_title_triplet(existing: list[str], report: dict, main_title: str) -> list[str]:
    """Find three distinct hooks from real verified topics, never fabricate one.

    Prefer retaining usable model proposals; sample evidence across the entire
    timeline, not just the first few minutes. Every triplet must pass the
    existing independent, source-grounded AB gate before being accepted.
    """
    from itertools import combinations

    blocks = list(report.get("blocks") or [])
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        title = " ".join(str(value or "").split())
        key = title.casefold()
        if (
            20 <= len(title) <= 100
            and key != str(main_title).strip().casefold()
            and key not in seen
        ):
            seen.add(key)
            candidates.append(title)

    for title in existing:
        add(title)
    if blocks:
        positions = sorted({
            int(i * (len(blocks) - 1) / 15) for i in range(16)
        })
        for pos in positions:
            block = blocks[pos]
            if block.get("verified") is not True:
                continue
            for item in (block.get("topics") or [])[:2]:
                if not isinstance(item, dict) or not str(item.get("evidence") or "").strip():
                    continue
                topic = " ".join(str(item.get("topic") or "").split())
                if 8 <= len(topic) <= 72:
                    add(topic + " | ЧАТ РУЛЕТКА")
                if len(candidates) >= 25:
                    break
            if len(candidates) >= 25:
                break
    for chosen in combinations(candidates, 3):
        if not ab_title_issues(chosen, report):
            return list(chosen)
    return []




def _no_missing_block_model(*_args, **_kwargs):
    raise RuntimeError("Private cached evidence missing: no full inference permitted")


def run(
    *, private_root: Path | None = None,
    db_path: Path | None = None,
    recover: Callable[..., list[str]] = _recover_title_variants,
) -> dict:
    result = {
        "schema": "RG_PRIVATE_AB_REPAIR_V1",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "NOT_READY",
        "youtube_data_api_calls": 0,
        "youtube_modified": False,
        "nas_modified": False,
        "captions_downloaded": False,
        "source_text_exported": False,
        "source_identifiers_exported": False,
        "generated_content_exported": False,
        "private_draft_updated": False,
        "ollama_title_calls": 0,
        "verified_topic_triplet_used": False,
        "evidence_blocks_verified": 0,
        "previous_ab_titles_count": 0,
        "candidate_ab_titles_count": 0,
        "previous_gate_warnings": -1,
        "candidate_gate_warnings": -1,
    }
    root = private_root or DEFAULT_PRIVATE_ROOT
    db = db_path or app_data_dir() / "rg_youtube_control.db"
    if not db.is_file():
        result["reason"] = "Missing local video metadata database"
        return result
    draft_root = root / "private_drafts"
    try:
        candidates = sorted(
            (
                p for p in draft_root.glob("*.json")
                if p.is_file() and re.fullmatch(r"[A-Za-z0-9_-]{11}", p.stem)
            ),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
    except OSError:
        candidates = []
    if not candidates:
        result["reason"] = "No private staged SEO draft to improve"
        return result
    for draft_path in candidates[:5]:
        video_id = draft_path.stem
        srt_path = root / "private_source" / (video_id + ".srt")
        if not srt_path.is_file():
            continue
        try:
            with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as conn:
                conn.execute("PRAGMA query_only=ON")
                source = cached_public_metadata(conn, video_id, "live")
            duration = int(source.get("duration") or 0)
            if (
                duration < MIN_LONG_LIVE_SECONDS
                or str(source.get("scheduled_publish_at") or "").strip()
                or str(source.get("privacy_status") or "public") != "public"
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
            captions = load_srt_transcript(srt_path)
            if not _captions_span_full_long_live(captions, duration):
                continue
            report = analyze_all_timeline_blocks(
                captions, model=DEFAULT_OLLAMA_MODEL,
                chat=_no_missing_block_model,
                cache_dir=root / "private_semantic_cache" / video_id,
                max_chars=5000, max_span_seconds=300,
            )
            if (
                report.get("source_integrity_verified") is not True
                or report.get("blocks_with_evidence") != report.get("blocks_total")
                or report.get("unverified_blocks")
                or report.get("cache_hits") != report.get("blocks_total")
            ):
                result["reason"] = "Verified evidence cache incomplete"
                return result
            result["evidence_blocks_verified"] = int(report["blocks_total"])
            package = dict(draft["package"])
            old_variants = list(package.get("title_variants") or [])
            result["previous_ab_titles_count"] = len(old_variants)
            def validate(variants):
                return review_seo_package(
                    title=str(package.get("title") or ""),
                    description=str(package.get("description") or ""),
                    variants=variants,
                    evidence_report=report,
                    original_description=str(draft.get("source_description") or ""),
                    original_tags=list(draft.get("source_tags") or []),
                    tags=list(package.get("tags") or []),
                )
            old_issues = validate(old_variants)
            result["previous_gate_warnings"] = len(old_issues)
            if len(old_variants) == 3 and not ab_title_issues(old_variants, report):
                result["status"] = "ALREADY_VALID_AB"
                result["reason"] = "Three grounded A/B titles already exist"
                return result
            result["ollama_title_calls"] = 1
            try:
                proposed = recover(
                    current_title=str(draft.get("source_title") or ""),
                    transcript=evidence_outline_text(report),
                    model=DEFAULT_OLLAMA_MODEL,
                )
            except (ValueError, RuntimeError, TimeoutError, TypeError, OSError):
                proposed = []
            proposed = [str(item).strip() for item in (proposed or []) if str(item).strip()]
            if len(proposed) != 3 or ab_title_issues(proposed, report):
                # Deterministic fallback: preserve existing choices when valid
                # and select others from ALL verified timeline sections.
                proposed = complete_grounded_ab_variants(
                    old_variants, report, main_title=str(package.get("title") or ""),
                )
                if len(proposed) != 3 or ab_title_issues(proposed, report):
                    proposed = choose_verified_title_triplet(
                        old_variants, report, str(package.get("title") or ""),
                    )
                    result["verified_topic_triplet_used"] = len(proposed) == 3
            result["candidate_ab_titles_count"] = len(proposed)
            if (
                len(proposed) != 3
                or any(v.casefold() == str(package.get("title") or "").casefold()
                       for v in proposed)
                or ab_title_issues(proposed, report)
            ):
                result["status"] = "REVIEW_REQUIRED"
                result["reason"] = "Focused title model did not produce 3 grounded alternatives"
                return result
            new_issues = validate(proposed)
            result["candidate_gate_warnings"] = len(new_issues)
            if len(new_issues) >= len(old_issues):
                result["status"] = "REVIEW_REQUIRED"
                result["reason"] = "Focused titles did not improve the complete quality gate"
                return result
            package["title_variants"] = proposed
            package["ab_quality_issues"] = []
            draft["package"] = package
            draft["issues"] = new_issues
            draft["review_required"] = True
            draft["youtube_modified"] = False
            tmp = draft_path.with_suffix(".ab-pending")
            tmp.write_text(json.dumps(draft, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(draft_path)
            result["private_draft_updated"] = True
            result["status"] = "IMPROVED_REVIEW_DRAFT"
            result["reason"] = "Three verified A/B alternatives saved privately for review"
            return result
        except (OSError, ValueError, TypeError, RuntimeError, sqlite3.Error):
            continue
    result["reason"] = "No complete private LIVE draft and cached source match"
    return result


def main() -> int:
    result = run()
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    for key in (
        "status", "evidence_blocks_verified", "previous_ab_titles_count",
        "candidate_ab_titles_count", "previous_gate_warnings",
        "candidate_gate_warnings", "private_draft_updated",
        "ollama_title_calls", "reason",
    ):
        print("PRIVATE AB REPAIR " + key.upper() + ":", result.get(key), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
