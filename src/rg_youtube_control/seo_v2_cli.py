"""Read-only command line entrypoint for claim-first universal SEO v3.

Usage:
  python -m rg_youtube_control.seo_v2_cli input.srt --output seo-preview.json

Never calls YouTube, publishes metadata, or modifies the input SRT.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .lm_studio_client import lm_studio_chat
from .seo_v3_pipeline import generate_claim_first_seo as generate_universal_seo


def _local_chat(prompt: str, *, model: str = "") -> dict[str, Any]:
    raw = lm_studio_chat(
        [
            {"role": "system", "content": (
                "Produce only valid JSON. Never invent facts or quotations. "
                "Return review-only metadata; no publication permission."
            )},
            {"role": "user", "content": prompt},
        ],
        # Quote extraction is recoverable from verbatim SRT. Never let
        # its model call consume the full editorial inference timeout.
        # A delayed title/review call still has the normal 180 s budget.
        model=model,
        timeout=(45 if prompt.startswith(
            "Extract up to three substantial verbatim statements"
        ) else 180),
        temperature=0.05,
        json_mode=True, max_tokens=4000, reasoning_effort="none",
    )
    return json.loads(raw)


def _save_json(path: Path, value: dict[str, Any]) -> None:
    """Write a complete preview atomically, never edit input source files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only universal SEO v2 preview")
    parser.add_argument("srt", type=Path, nargs="?")
    parser.add_argument("--input-dir", type=Path,
                        help="Process all .srt files in a folder sequentially")
    parser.add_argument("--output", type=Path,
                        help="Output file for a single SRT")
    parser.add_argument("--output-dir", type=Path,
                        help="Directory for separate batch JSON previews")
    parser.add_argument("--limit", type=int, default=100,
                        help="Maximum files in one batch, default 100")
    parser.add_argument("--model", default=os.getenv("RG_LMSTUDIO_MODEL", ""))
    parser.add_argument("--reviewer-model",
                        default=os.getenv("RG_SEO_REVIEWER_MODEL", ""))
    args = parser.parse_args(argv)
    if bool(args.srt) == bool(args.input_dir):
        parser.error("Specify one SRT file or --input-dir, not both")
    if args.srt and args.output_dir:
        parser.error("--output-dir is only for --input-dir")
    if args.input_dir and args.output:
        parser.error("--output is only for one SRT")
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")

    if args.input_dir:
        if not args.input_dir.is_dir():
            parser.error("--input-dir must be an existing directory")
        sources = sorted(
            (path for path in args.input_dir.iterdir()
             if path.is_file() and path.suffix.casefold() == ".srt"),
            key=lambda path: path.name.casefold(),
        )[:args.limit]
        if not sources:
            parser.error("No SRT files found in the input directory")
        destination = args.output_dir or args.input_dir / "seo_v2_previews"
    else:
        if not args.srt.is_file():
            parser.error("SRT file not found")
        sources = [args.srt]
        destination = None

    candidate = lambda prompt: _local_chat(prompt, model=args.model)
    critic = lambda prompt: _local_chat(
        prompt, model=args.reviewer_model or args.model
    )
    results: list[dict[str, Any]] = []
    for source in sources:
        output = (
            destination / (source.stem + ".seo_v2_review.json")
            if destination is not None else
            args.output or source.with_suffix(".seo_v2_review.json")
        )
        try:
            srt_text = source.read_text(encoding="utf-8-sig")
            result = generate_universal_seo(
                srt_text, candidate, independent_review=critic,
            )
            status = str(result.get("status") or "REVIEW_REQUIRED")
            _save_json(output, result)
            item = {
                "source": source.name, "status": status,
                "output": str(output),
                "source_cues": result["evidence"]["source_cues"],
                "verified_quotes": len(result["evidence"]["accepted"]),
                "publication_allowed": False,
            }
        except (ValueError, RuntimeError, OSError, UnicodeError) as exc:
            # Continue past isolated corrupt SRTs or model failures. Keep the
            # exception type without exposing transcript or private payload.
            item = {
                "source": source.name, "status": "FAILED_REVIEW_REQUIRED",
                "error_type": type(exc).__name__,
                "publication_allowed": False,
            }
        results.append(item)
        print(json.dumps(item, ensure_ascii=False))
    if destination is not None:
        _save_json(destination / "_batch_summary.json", {
            "schema": "RG_SEO_V2_BATCH_PREVIEW",
            "count": len(results),
            "results": results,
            "publication_allowed": False,
        })
    return 0 if all(
        item["status"] == "READY_FOR_HUMAN_REVIEW" for item in results
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
