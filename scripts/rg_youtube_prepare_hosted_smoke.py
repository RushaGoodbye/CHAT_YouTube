"""Generate a deterministic, non-AI proposal for GitHub-hosted isolation QA.

Synthetic fingerprint regression only; no source edits or local Ollama calls.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "src/rg_youtube_control/seo_quality_gate.py",
    "src/rg_youtube_control/rejected_seo.py",
)
NEEDLE = 'return hashlib.sha256(raw.encode("utf-8")).hexdigest()'


def main() -> int:
    originals = {name: (ROOT / name).read_text(encoding="utf-8") for name in FILES}
    assert originals[FILES[1]].count(NEEDLE) == 1, "Fingerprint drill fixture changed"
    proposal = {
        "schema": "RG_YOUTUBE_PROPOSAL_V1",
        "status": "PROPOSED_UNVERIFIED",
        "drill": True,
        "base_sha256": {
            name: hashlib.sha256(source.encode("utf-8")).hexdigest()
            for name, source in originals.items()
        },
        "files": {FILES[1]: originals[FILES[1]]},
    }
    (ROOT / "rg_youtube_proposed_candidate.json").write_text(
        json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Prepared deterministic GitHub-hosted drill; no source files changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
