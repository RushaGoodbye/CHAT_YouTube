"""Constrained local Ollama repair agent for RG YouTube Control.

Runs only in a disposable GitHub Actions workspace, never installs software to
the user's running application, and never publishes to YouTube.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WRITABLE = (
    "src/rg_youtube_control/seo_quality_gate.py",
    "src/rg_youtube_control/rejected_seo.py",
 )
ALLOWED = WRITABLE + (
    "tests/test_seo_quality_gate.py",
    "tests/test_rejected_seo.py",
    "tests/test_review_quality_accept.py",
    "tests/test_content_vs_technical_review.py",
    "tests/test_seo_preview_ab_contract.py",
)
TESTS = [f for f in ALLOWED if f.startswith("tests/")]


def run_tests():
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    return proc.returncode, (proc.stdout + "\n" + proc.stderr)[-12000:]


def ask_model(failures: str) -> dict:
    sources = {p: (ROOT / p).read_text(encoding="utf-8") for p in ALLOWED}
    prompt = (
        "Fix the reported Python test failures with the smallest safe patch. "
        "Only touch existing allowed files; never disable checks, tests, or security. "
        "Return ONLY JSON: {\"files\": {\"path\": \"full file contents\"}}. "
        "If the repair is uncertain, return {\"files\": {}}.\n"
        "Allowed source files:\n" + json.dumps(sources, ensure_ascii=False) +
        "\nFailures:\n" + failures
    )
    payload = json.dumps({
        "model": os.environ.get("RG_REPAIR_MODEL", "qwen3:8b"),
        "prompt": prompt, "stream": False, "format": "json",
        "options": {"temperature": 0.1, "num_predict": 6000},
    }).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate", payload,
        {"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        data = json.loads(response.read())
    return json.loads(data["response"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Allow sandbox repairs (never auto-merge)")
    args = parser.parse_args()
    before, failure_text = run_tests()
    Path("rg_seo_repair_report.json").write_text(
        json.dumps({"initial_tests_pass": before == 0,
                    "mode": "apply" if args.apply else "dry_run"},
                   indent=2), encoding="utf-8"
    )
    if before == 0:
        print("PASS: no repair needed")
        return 0
    if not args.apply:
        print("FAIL: dry-run mode, no code changed")
        return 1
    try:
        proposed = ask_model(failure_text).get("files", {})
        if not isinstance(proposed, dict) or not proposed:
            print("No safe repair proposed")
            return 1
        if len(proposed) > 3 or any(p not in WRITABLE for p in proposed):
            raise ValueError("Model attempted edits outside allowlist or change limit")
        originals = {}
        for path, value in proposed.items():
            if not isinstance(value, str) or len(value) > 120_000:
                raise ValueError("Invalid replacement file")
            originals[path] = (ROOT / path).read_text(encoding="utf-8")
            compile(value, path, "exec")
        try:
            for path, value in proposed.items():
                (ROOT / path).write_text(value, encoding="utf-8")
            after, log = run_tests()
            if after != 0:
                print("Repair failed verification: " + log[-1500:])
                return 1
            print("PASS: patched sandbox passes safety tests")
            return 0
        finally:
            if "after" not in locals() or after != 0:
                for path, value in originals.items():
                    (ROOT / path).write_text(value, encoding="utf-8")
    except Exception as exc:
        print("Repair blocked: " + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
