"""Validate an untrusted Ollama proposal ONLY on an ephemeral GitHub-hosted runner.

Never use this validator on the user's desktop or self-hosted GitHub runner.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "rg_youtube_proposed_candidate.json"
REPORT = ROOT / "rg_youtube_hosted_validation.json"
WRITABLE = (
    "src/rg_youtube_control/seo_quality_gate.py",
    "src/rg_youtube_control/rejected_seo.py",
)
TARGETED = [
    "tests/test_seo_quality_gate.py",
    "tests/test_rejected_seo.py",
    "tests/test_review_quality_accept.py",
    "tests/test_content_vs_technical_review.py",
    "tests/test_seo_preview_ab_contract.py",
]


def main() -> int:
    # Fail closed if launched in a self-hosted or unmanaged environment.
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        print("BLOCKED: candidate evaluation requires a GitHub-hosted runner", flush=True)
        return 2
    report = {"schema": "RG_YOUTUBE_HOSTED_VALIDATION_V1", "status": "BLOCKED"}
    original: dict[str, str] = {}
    try:
        payload = json.loads(CANDIDATE.read_text(encoding="utf-8"))
        if payload.get("schema") != "RG_YOUTUBE_PROPOSAL_V1" or payload.get("status") != "PROPOSED_UNVERIFIED":
            raise ValueError("Unexpected proposal format or status")
        proposed = payload.get("files")
        base_hashes = payload.get("base_sha256")
        if not isinstance(proposed, dict) or not proposed or len(proposed) > 2:
            raise ValueError("Missing or oversized proposal")
        if not isinstance(base_hashes, dict) or any(p not in WRITABLE for p in proposed):
            raise ValueError("Unexpected candidate paths")
        for name in WRITABLE:
            path = ROOT / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("Unexpected source path")
            current = path.read_text(encoding="utf-8")
            if hashlib.sha256(current.encode("utf-8")).hexdigest() != base_hashes.get(name):
                raise ValueError("Candidate was produced for a different checkout")
            original[name] = current
        is_drill = payload.get("drill") is True
        if is_drill:
            fingerprint = ROOT / "src/rg_youtube_control/rejected_seo.py"
            needle = 'return hashlib.sha256(raw.encode("utf-8")).hexdigest()'
            if original["src/rg_youtube_control/rejected_seo.py"].count(needle) != 1:
                raise ValueError("Synthetic drill invariant changed")
            fingerprint.write_text(
                original["src/rg_youtube_control/rejected_seo.py"].replace(
                    needle, 'return "broken-fingerprint"'
                ), encoding="utf-8"
            )
        for name, content in proposed.items():
            if not isinstance(content, str) or len(content) > 120_000:
                raise ValueError("Invalid source contents")
            compile(content, name, "exec")
            (ROOT / name).write_text(content, encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "QT_QPA_PLATFORM": "offscreen"}
        for label, paths in (("targeted", TARGETED), ("full", ["tests"])):
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *paths, "--tb=short"],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=240,
            )
            log = (proc.stdout + "\n" + proc.stderr)[-5500:]
            print(label.upper(), "EXIT", proc.returncode, log, flush=True)
            report[label + "_pass"] = proc.returncode == 0
            if proc.returncode != 0:
                report["error"] = label + " tests failed: " + log[-3000:]
                return 1
        report["status"] = "DRILL_PASS" if is_drill else "VALIDATED_FOR_REVIEW"
        print("HOSTED VALIDATION:", report["status"], flush=True)
        return 0
    except Exception as exc:
        report["error"] = str(exc)[:1500]
        print("HOSTED VALIDATION BLOCKED:", report["error"], flush=True)
        return 2
    finally:
        REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        # Not required for ephemeral runners but makes failures deterministic.
        for name, text in original.items():
            (ROOT / name).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
