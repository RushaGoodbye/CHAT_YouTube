"""Read-only command line entrypoint for universal SEO v2.

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
from .seo_v2_pipeline import generate_universal_seo


def _local_chat(prompt: str, *, model: str = "") -> dict[str, Any]:
    raw = lm_studio_chat(
        [
            {"role": "system", "content": (
                "Produce only valid JSON. Never invent facts or quotations. "
                "Return review-only metadata; no publication permission."
            )},
            {"role": "user", "content": prompt},
        ],
        model=model, timeout=180, temperature=0.05,
        json_mode=True, max_tokens=4000, reasoning_effort="none",
    )
    return json.loads(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only universal SEO v2 preview")
    parser.add_argument("srt", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default=os.getenv("RG_LMSTUDIO_MODEL", ""))
    parser.add_argument("--reviewer-model",
                        default=os.getenv("RG_SEO_REVIEWER_MODEL", ""))
    args = parser.parse_args(argv)
    srt = args.srt.read_text(encoding="utf-8-sig")
    candidate = lambda prompt: _local_chat(prompt, model=args.model)
    critic = lambda prompt: _local_chat(
        prompt, model=args.reviewer_model or args.model
    )
    result = generate_universal_seo(srt, candidate, independent_review=critic)
    output = args.output or args.srt.with_suffix(".seo_v2_review.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": result["status"], "output": str(output),
        "source_cues": result["evidence"]["source_cues"],
        "verified_quotes": len(result["evidence"]["accepted"]),
        "publication_allowed": False,
    }, ensure_ascii=False))
    return 0 if result["status"] == "READY_FOR_HUMAN_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
