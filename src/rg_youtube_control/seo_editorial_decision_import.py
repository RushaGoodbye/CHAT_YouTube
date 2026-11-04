"""Safely import editorial decisions; never change SEO metadata or publish.

Usage:
python -m rg_youtube_control.seo_editorial_decision_import handoff.json decisions.json validated.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .seo_editorial_decisions import validate_editorial_decisions


def import_review_decisions(
    *, handoff_file: str | Path, decisions_file: str | Path,
    output_file: str | Path,
) -> dict:
    handoff_path = Path(handoff_file)
    decisions_path = Path(decisions_file)
    target = Path(output_file)
    if target.resolve() in (handoff_path.resolve(), decisions_path.resolve()):
        raise ValueError("OUTPUT_CANNOT_OVERWRITE_REVIEW_SOURCE")
    packet = json.loads(handoff_path.read_text(encoding="utf-8-sig"))
    submission = json.loads(decisions_path.read_text(encoding="utf-8-sig"))
    result = validate_editorial_decisions(packet=packet, submission=submission)
    target.parent.mkdir(parents=True, exist_ok=True)
    # A validated handoff remains a staged human-review artifact only.
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline G2 editorial review import")
    parser.add_argument("handoff_file")
    parser.add_argument("decisions_file")
    parser.add_argument("output_file")
    args = parser.parse_args()
    result = import_review_decisions(
        handoff_file=args.handoff_file, decisions_file=args.decisions_file,
        output_file=args.output_file,
    )
    print("G2_EDITORIAL_IMPORT_PASS",
          "REVIEWED", result["reviewed"], "PENDING", result["pending"],
          "G2_ACCEPTED", result["g2_accepted"],
          "PUBLICATION_ALLOWED", result["publication_allowed"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
