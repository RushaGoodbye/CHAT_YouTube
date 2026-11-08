"""Safely import offline G2 editorial decisions, preserving every review snapshot.

A browser may create files named RG_G2_HUMAN_DECISIONS (2).json. The latest
export is selected by file modification time, with no fallback to stale files.
Source, candidate, and reviewer hashes are validated before any write.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .seo_editorial_decisions import validate_editorial_decisions

_EXPORT = re.compile(r"RG_G2_HUMAN_DECISIONS(?: \((\d+)\))?\.json", re.IGNORECASE)


def latest_decisions_export(downloads: str | Path) -> Path:
    base = Path(downloads)
    if not base.is_dir():
        raise ValueError("MISSING_DOWNLOADS_DIRECTORY")
    candidates = [p for p in base.iterdir()
                  if p.is_file() and not p.is_symlink() and _EXPORT.fullmatch(p.name)]
    if not candidates:
        raise ValueError("NO_EDITORIAL_DECISION_EXPORT")
    # Filename suffix is not reliable when files are renamed; mtime is.
    scored = sorted(((p.stat().st_mtime_ns, p) for p in candidates),
                    key=lambda item: item[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        raise ValueError("AMBIGUOUS_LATEST_EXPORT")
    return scored[0][1]


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
    # A validation report is evidence of what was imported and must never
    # silently overwrite an older decision snapshot.
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    return result


def import_latest_review_decisions(
    *, handoff_file: str | Path, downloads: str | Path,
    output_dir: str | Path,
) -> tuple[Path, Path, dict]:
    latest = latest_decisions_export(downloads)
    # Unique timestamp from the actual export preserves multiple review runs.
    destination = Path(output_dir) / (
        "G2_EDITORIAL_VALIDATED_" + str(latest.stat().st_mtime_ns) + ".json"
    )
    result = import_review_decisions(
        handoff_file=handoff_file, decisions_file=latest,
        output_file=destination,
    )
    return latest, destination, result


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline G2 editorial review import")
    parser.add_argument("--latest-downloads", metavar="DIRECTORY")
    parser.add_argument("handoff_file")
    parser.add_argument("path2")
    parser.add_argument("path3", nargs="?")
    args = parser.parse_args()
    if args.latest_downloads:
        if args.path3 is not None:
            parser.error("--latest-downloads expects HANDOFF_FILE OUTPUT_DIR")
        source, destination, result = import_latest_review_decisions(
            handoff_file=args.handoff_file,
            downloads=args.latest_downloads,
            output_dir=args.path2,
        )
        print("SOURCE_EXPORT", source.name, "VALIDATED_REPORT", destination.name)
    else:
        if args.path3 is None:
            parser.error("Expected HANDOFF_FILE DECISIONS_FILE OUTPUT_FILE")
        result = import_review_decisions(
            handoff_file=args.handoff_file,
            decisions_file=args.path2,
            output_file=args.path3,
        )
    print("G2_EDITORIAL_IMPORT_PASS",
          "REVIEWED", result["reviewed"], "PENDING", result["pending"],
          "G2_ACCEPTED", result["g2_accepted"],
          "PUBLICATION_ALLOWED", result["publication_allowed"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
