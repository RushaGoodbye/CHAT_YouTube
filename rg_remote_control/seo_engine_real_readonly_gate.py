"""Real RG SEO Engine 1.0 pilot: actual Ollama, exact-ID captions, no writes.

This test deliberately does not call save_optimization_draft, update YouTube,
modify the app database or trust filename/title similarity.
The output in RUNNER_TEMP is a review-only, source-sensitive report.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

if __package__:
    from .seo_readonly_acceptance_10 import get_video_inputs
else:
    from seo_readonly_acceptance_10 import get_video_inputs
from rg_youtube_control.free_tools import load_srt_transcript, fetch_transcript
from rg_youtube_control.optimization import validate_content_package, safe_description_fix
from rg_youtube_control.seo_engine_ollama import generate_with_ollama
from rg_youtube_control.seo_source_alignment import check_title_against_transcript


def run_one(video_id: str, *, database: Path, model: str,
            preflight_only: bool = False) -> dict:
    started = time.monotonic()
    report = {
        "video_id": video_id,
        "engine": "RG_SEO_ENGINE_1_0",
        "status": "BLOCKED",
        "stage": "metadata",
        "youtube_writes": 0,
        "production_db_writes": 0,
        "production_draft_writes": 0,
        "review_required": True,
    }
    try:
        meta = get_video_inputs(database, video_id)
        title = meta["title"].strip()
        if not title:
            raise ValueError("MISSING_TITLE")
        report["stage"] = "load_exact_id_captions"
        nas = Path(meta["transcript_root"]) / (video_id + ".srt")
        if nas.is_file():
            rows = load_srt_transcript(nas)
            source_kind = "nas_exact_video_id"
        else:
            # Read-only public caption fallback, exact video ID only.
            rows = fetch_transcript(video_id)
            source_kind = "public_exact_video_id"
        if len(rows) < 10:
            raise ValueError("INSUFFICIENT_CAPTION_ROWS")
        text = " ".join(str(row.get("text") or "") for row in rows)
        if len(text.strip()) < 150:
            raise ValueError("CAPTION_TEXT_TOO_SHORT")
        last = max(float(r.get("start") or 0) +
                   float(r.get("duration") or 0) for r in rows)
        duration = int(meta["duration"])
        if duration > 0 and last < duration * 0.75:
            raise ValueError("CAPTIONS_INCOMPLETE")
        aligned = check_title_against_transcript(title, text)
        if aligned.missing:
            raise ValueError("SOURCE_TITLE_MISMATCH")
        report.update(source=source_kind, caption_rows=len(rows),
                      source_chars=len(text), video_seconds=duration,
                      last_caption_second=round(last, 1))
        if preflight_only:
            report["stage"] = "source_preflight_pass"
            report["status"] = "SOURCE_READY"
            report["elapsed_seconds"] = round(time.monotonic() - started, 1)
            return report
        report["stage"] = "actual_local_ollama"
        draft = generate_with_ollama(
            video_id=video_id, current_title=title, transcript=text,
            model=model,
        )
        report["stage"] = "production_ui_contract"
        # Match the same normalization and validation invoked in the GUI;
        # do not persist or publish anything.
        final_description = safe_description_fix(draft.description, draft.title).after
        check = validate_content_package(
            draft.title, final_description, draft.chapters,
            list(draft.tags), list(draft.ab_titles),
        )
        report.update(
            ab_title_count=len(draft.ab_titles),
            tags_count=len(draft.tags),
            description_chars=len(final_description),
            title=draft.title,
            ab_titles=list(draft.ab_titles),
            description_excerpt=final_description[:600],
            tags=list(draft.tags),
            ui_error_count=len(check.errors),
            ui_warning_count=len(check.warnings),
            chapters_provided=bool(draft.chapters),
        )
        if not check.ready:
            raise ValueError("UI_PACKAGE_CONTRACT_FAILURE")
        report["status"] = "DRAFT_REVIEW_REQUIRED"
        report["stage"] = "finished"
    except Exception as exc:
        # Do not upload arbitrary exception strings that may contain
        # local filesystem paths, private captions, or model output.
        report["error_type"] = type(exc).__name__
        error = str(exc)
        source_codes = {
            "MISSING_TITLE", "INSUFFICIENT_CAPTION_ROWS",
            "CAPTION_TEXT_TOO_SHORT", "CAPTIONS_INCOMPLETE",
            "SOURCE_TITLE_MISMATCH", "UI_PACKAGE_CONTRACT_FAILURE",
        }
        if isinstance(exc, ValueError) and error in source_codes:
            code = error
        elif report["stage"] == "actual_local_ollama":
            if type(exc).__name__ in {"URLError", "HTTPError", "TimeoutError"}:
                code = "OLLAMA_CONNECTION_OR_TIMEOUT"
            elif type(exc).__name__ == "JSONDecodeError":
                code = "OLLAMA_INVALID_JSON"
            elif isinstance(exc, ValueError):
                code = "OLLAMA_RESPONSE_FAILED_CONTRACT"
            else:
                code = "OLLAMA_GENERATION_FAILURE"
        else:
            code = "SOURCE_OR_VALIDATION_FAILURE"
        report["error_code"] = code
    report["elapsed_seconds"] = round(time.monotonic() - started, 1)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-ids", nargs="+", default=["MEitKm687xo"])
    parser.add_argument("--db", type=Path, default=(
        Path(os.environ.get("LOCALAPPDATA", ".")) /
        "RGYouTubeControl" / "rg_youtube_control.db"
    ))
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--pilot-first-eligible", action="store_true")
    parser.add_argument("--output", type=Path, default=(
        Path(os.environ.get("RUNNER_TEMP", ".")) / "rg_seo_engine_actual.json"
    ))
    args = parser.parse_args()
    # A CSV-shaped single argument safely carries YouTube IDs that begin
    # with '-' through PowerShell and argparse.
    args.video_ids = [
        video_id for group in args.video_ids
        for video_id in group.split(",") if video_id
    ]
    results = []
    def save() -> None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "schema": "RG_SEO_ENGINE_ACTUAL_READONLY_V1",
            "read_only": True,
            "pilot_first_eligible": args.pilot_first_eligible,
            "results": results,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.pilot_first_eligible:
        # Scan all sources without invoking Ollama and run the model only
        # for the FIRST video which passes source/title/coverage checks.
        for video_id in args.video_ids:
            result = run_one(video_id, database=args.db, model=args.model,
                             preflight_only=True)
            results.append(result)
            print(json.dumps({"video_id": video_id, "status": result["status"],
                              "stage": result["stage"],
                              "error_code": result.get("error_code")}), flush=True)
            save()
        first = next((i for i, row in enumerate(results)
                      if row["status"] == "SOURCE_READY"), None)
        if first is not None:
            result = run_one(results[first]["video_id"], database=args.db,
                             model=args.model)
            results[first] = result
            print(json.dumps({"pilot_video": result["video_id"],
                              "status": result["status"],
                              "stage": result["stage"],
                              "error_code": result.get("error_code")}), flush=True)
            save()
        return 0 if first is not None and results[first]["status"] == "DRAFT_REVIEW_REQUIRED" else 2

    for video_id in args.video_ids:
        result = run_one(video_id, database=args.db, model=args.model)
        results.append(result)
        print(json.dumps({"video_id": video_id, "status": result["status"],
                          "stage": result["stage"],
                          "error_code": result.get("error_code")}), flush=True)
        save()
    return 0 if results and all(
        row["status"] == "DRAFT_REVIEW_REQUIRED" for row in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
