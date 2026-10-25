"""Ten real-video SEO acceptance on the creator's existing Windows machine.

READ-ONLY: opens the app's SQLite database with mode=ro/query_only and
reads only configured NAS SRT files. It neither imports drafts nor calls any
YouTube endpoint. QA caches/reports live exclusively in RUNNER_TEMP.

Passing this machine check means *structurally eligible for human review*.
It never means the titles are approved, or that content was published.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rg_youtube_control.config import DEFAULT_NAS_TRANSCRIPTS_PATH
from rg_youtube_control.dialogue_seo import (ab_title_issues,
                                              analyze_all_timeline_blocks,
                                              evidence_outline_text)
from rg_youtube_control.free_tools import (DEFAULT_OLLAMA_MODEL,
                                           generate_seo_package_local,
                                           load_srt_transcript, ollama_chat,
                                           _description_quality_error)
def _incidental_ab_quote(title: str) -> bool:
    """Reject incidental pleasantries and appearance-based SEO headlines."""
    text = " ".join(str(title or "").casefold().split())
    return bool(re.search(
        r"(?:\\bкак\\s+дела\\b|\\bкак\\s+поживаете\\b|"
        r"\\bпривет(?:ствую)?\\b|\\bздравствуй(?:те)?\\b|"
        r"\\bдо\\s+свидания\\b|\\bспасибо\\s+за\\s+(?:разговор|беседу)\\b|"
        r"\\bяк\\s+справи\\b|\\bдякую\\s+за\\s+розмову\\b|"
        r"\\b(?:выглядишь|выглядите|виглядаєш|виглядаєте)\\b|"
        r"\\b(?:красивый|красивая|красивые|красивий|красива|гарна|гарний)\\b|"
        r"\\b(?:внешность|зовнішність)\\b|"
        r"\\b(?:твои|ваши|твої|ваші)\\s+(?:глаза|волосы|очі|волосся)\\b)",
        text,
    ))
from rg_youtube_control.optimization import safe_description_fix

MAIN_IDS = (
    "MEitKm687xo", "u9y_f4HtEbQ", "dmDUcD1unbM",
    "MClldsur_0s", "ZstT-QQyacA", "LM0vkW9YoKg",
    "GQL6N4jQpI8", "-Bu_aDIvEs4", "mdPMyIy5A70",
    "DywWeHtnuhM",
)
LIVE_IDS = ("4ItkxMPI1GA", "fdHXrCyw3Lw")
VALID_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def get_video_inputs(db_file: Path, video_id: str) -> dict:
    """Read public metadata + NAS configuration with no SQLite mutations."""
    if not VALID_ID.fullmatch(video_id):
        raise ValueError("Invalid video ID")
    uri = db_file.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=12) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        row = db.execute(
            "SELECT video_id,profile,title,duration FROM videos WHERE video_id=?",
            (video_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Video ID not present in app's synchronized database")
        setting = db.execute(
            "SELECT value FROM settings WHERE key='nas_transcripts_path'"
        ).fetchone()
        configured = str(setting["value"] or "").strip() if setting else ""
        return {
            "video_id": video_id,
            "profile": str(row["profile"] or ""),
            "title": str(row["title"] or ""),
            "duration": int(row["duration"] or 0),
            "transcript_root": configured or DEFAULT_NAS_TRANSCRIPTS_PATH,
        }


def run_one(
    video_id: str,
    *,
    database: Path,
    qa_cache: Path,
    model: str = DEFAULT_OLLAMA_MODEL,
) -> dict:
    started = time.monotonic()
    result = {
        "video_id": video_id,
        "status": "BLOCKED",
        "youtube_api_calls": 0,
        "youtube_writes": 0,
        "production_db_writes": 0,
        "production_draft_writes": 0,
        "review_required": True,
    }
    try:
        metadata = get_video_inputs(database, video_id)
        result["profile"] = metadata["profile"]
        title = metadata["title"]
        if not title:
            raise RuntimeError("Video metadata has no title")
        folder = Path(metadata["transcript_root"])
        srt = folder / (video_id + ".srt")
        if not srt.is_file():
            raise RuntimeError("NAS SRT missing; no YouTube fallback is allowed in QA")
        rows = load_srt_transcript(srt)
        if len(rows) < 10:
            raise RuntimeError("Incomplete SRT: fewer than ten caption rows")
        duration = metadata["duration"]
        last_second = max(
            float(row.get("start") or 0) + float(row.get("duration") or 0)
            for row in rows
        )
        if duration > 0 and last_second < duration * 0.75:
            raise RuntimeError(
                "SRT coverage below 75% of synchronized video duration"
            )
        report = analyze_all_timeline_blocks(
            rows,
            model=model,
            chat=ollama_chat,
            cache_dir=qa_cache / video_id,
            timeout=180.0,
        )
        blocks = int(report.get("blocks_total") or 0)
        grounded = int(report.get("blocks_with_evidence") or 0)
        result.update(
            {
                "srt_cues": len(rows),
                "video_duration_seconds": duration,
                "last_caption_second": round(last_second, 1),
                "timeline_blocks": blocks,
                "grounded_blocks": grounded,
            }
        )
        if grounded == 0:
            raise RuntimeError("No evidence-backed dialogue blocks")
        package = generate_seo_package_local(
            current_title=title,
            current_description="",
            current_tags=[],
            transcript=evidence_outline_text(report),
            public_context={"title": title, "duration": duration},
            model=model,
            is_short=duration <= 70,
            fast_mode=False,
            timeout=240.0,
            evidence_report=report,
        )
        main = str(package.get("title") or "")
        ab = list(package.get("title_variants") or [])
        description = str(package.get("description") or "")
        tags = list(package.get("tags") or [])
        issues = ab_title_issues(ab, report) if ab else ["Missing A/B titles"]
        quality = _description_quality_error(
            description, evidence_outline_text(report), max_chars=950
        )
        preview = safe_description_fix(description, main).after
        conditions = {
            "three_ab_titles": len(ab) == 3,
            "ab_grounded": not issues,
            "no_incidental_headlines": not any(
                _incidental_ab_quote(t) for t in [main] + ab
            ),
            "description_quality": not quality,
            "eight_tags": len(tags) >= 8,
            "full_timeline_with_evidence": grounded == blocks,
            "channel_links": "links.rginfoua.pp.ua" in preview,
            "donation_links": "donate.rginfoua.pp.ua" in preview,
        }
        result.update({
            "checks": conditions,
            "ab_count": len(ab),
            "tags_count": len(tags),
            "description_length": len(description),
            "flagged_topic_count": len(package.get(
                "evidence_editorial_review") or []),
            "status": (
                "DRAFT_READY_FOR_HUMAN_REVIEW"
                if all(conditions.values())
                else "NEEDS_REVIEW"
            ),
        })
    except Exception as exc:
        # The result is uploaded as a CI artifact. Never echo captions,
        # a local NAS path, an Ollama response or an exception containing
        # someone else's words into that public/private GitHub artifact.
        known = (
            "Invalid video ID",
            "Video ID not present in app's synchronized database",
            "Video metadata has no title",
            "NAS SRT missing; no YouTube fallback is allowed in QA",
            "Incomplete SRT: fewer than ten caption rows",
            "SRT coverage below 75% of synchronized video duration",
            "No evidence-backed dialogue blocks",
        )
        message = str(exc)
        result["error_type"] = type(exc).__name__
        result["error"] = (
            message if message in known
            else "Local content-validation or dependency failure; "
                 "review details on the source machine"
        )
    result["elapsed_seconds"] = round(time.monotonic() - started, 1)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-ids", nargs="+", default=list(MAIN_IDS))
    parser.add_argument("--db", type=Path, default=(
        Path(os.environ.get("LOCALAPPDATA", ".")) /
        "RGYouTubeControl" / "rg_youtube_control.db"
    ))
    parser.add_argument(
        "--output", type=Path,
        default=Path(os.environ.get("RUNNER_TEMP", ".")) / "rg_seo_qa_summary.json",
    )
    parser.add_argument("--model", default=DEFAULT_OLLAMA_MODEL)
    args = parser.parse_args(argv)
    qa_cache = Path(os.environ.get("RUNNER_TEMP", ".")) / "rg_seo_qa_cache"
    checked = []
    for video_id in args.video_ids:
        checked.append(run_one(
            video_id, database=args.db, qa_cache=qa_cache, model=args.model
        ))
    status = "READY_FOR_HUMAN_REVIEW" if checked and all(
        row["status"] == "DRAFT_READY_FOR_HUMAN_REVIEW" for row in checked
    ) else "BLOCKED"
    summary = {
        "schema": "RG_SEO_REAL_READONLY_ACCEPTANCE_V1",
        "status": status,
        "read_only": True,
        "video_count": len(checked),
        "results": checked,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=True), flush=True)
    return 0 if status == "READY_FOR_HUMAN_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
