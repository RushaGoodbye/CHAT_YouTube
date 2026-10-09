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


def run_tests(*, full_suite: bool = False):
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *(["tests"] if full_suite else TESTS)],
        cwd=ROOT, capture_output=True, text=True, timeout=600 if full_suite else 180,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    return proc.returncode, (proc.stdout + "\n" + proc.stderr)[-12000:]


def ask_model(failures: str, feedback: str = "") -> dict:
    # Include production source and its direct test only; avoid overflowing 4K model context.
    selected = [p for p in WRITABLE if p.split("/")[-1].replace(".py", "") in failures]
    if not selected:
        selected = list(WRITABLE)
    test_paths = ["tests/test_" + p.split("/")[-1] for p in selected]
    sources = {p: (ROOT / p).read_text(encoding="utf-8") for p in selected + test_paths if (ROOT / p).is_file()}
    prompt = (
        "Fix the reported Python test failures with the smallest safe patch. "
        "Only touch existing allowed files; never disable checks, tests, or security. "
        "Preserve ALL behavior described by existing tests. In particular, fingerprint "
        "tags must be case-insensitive, order-independent and deduplicated; "
        "fingerprints must change when the content changes. "
        "A constant hash or hashing the original unsorted/case-sensitive tags is WRONG. "
        "Return ONLY JSON: {\"files\": {\"path\": \"full file contents\"}}. "
        "If the repair is uncertain, return {\"files\": {}}.\n"
        "Context (tests are read-only):\n" + json.dumps(sources, ensure_ascii=False) +
        "\nFailures:\n" + failures[-3000:] + "\nPrevious candidate test failures:\n" + feedback[-1800:]
    )
    payload = json.dumps({
        "model": os.environ.get("RG_REPAIR_MODEL", "qwen3:8b"),
        "prompt": prompt, "stream": False, "format": "json", "think": False,
        "options": {"temperature": 0.1, "num_ctx": 8192, "num_predict": 2400},
    }).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate", payload,
        {"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        data = json.loads(response.read())
    print("MODEL RESPONSE:", "done_reason=", data.get("done_reason"),
          "eval_count=", data.get("eval_count"),
          "prompt_eval_count=", data.get("prompt_eval_count"),
          "response_chars=", len(data.get("response") or ""), flush=True)
    answer = json.loads(data["response"])
    if not isinstance(answer, dict):
        raise ValueError("Model response must be an object")
    print("MODEL PROPOSAL FILES:", list((answer.get("files") or {}).keys()), flush=True)
    return answer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Allow sandbox repairs (never auto-merge)")
    args = parser.parse_args()
    before, failure_text = run_tests()
    baseline_full, baseline_log = run_tests(full_suite=True)
    print("BASELINE FULL SUITE:", "PASS" if baseline_full == 0 else "FAIL", flush=True)
    if baseline_full != 0:
        print("BASELINE FULL DETAILS:", baseline_log[-2500:], flush=True)
    Path("rg_seo_repair_report.json").write_text(
        json.dumps({"initial_tests_pass": before == 0,
                    "mode": "apply" if args.apply else "dry_run"},
                   indent=2), encoding="utf-8"
    )
    if baseline_full != 0:
        print("BLOCKED: baseline full suite fails; repair cannot be validated", flush=True)
        return 2
    if before == 0:
        print("PASS: no repair needed")
        return 0
    if not args.apply:
        print("FAIL: dry-run mode, no code changed")
        return 1
    originals = {p: (ROOT / p).read_text(encoding="utf-8") for p in WRITABLE}
    feedback = ""
    succeeded = False
    try:
        for attempt in range(1, 3):
            # Never stack unverified AI patches; each try starts from the failing baseline.
            for p, original in originals.items():
                (ROOT / p).write_text(original, encoding="utf-8")
            print(f"REPAIR ATTEMPT {attempt}/2", flush=True)
            proposed = ask_model(failure_text, feedback).get("files", {})
            if not isinstance(proposed, dict) or not proposed:
                feedback = "Your prior response had an empty files object. The tests still fail. Provide an actual minimal fix to the production file or explicitly state uncertainty."
                print("No repair proposal; retrying with explicit failure context", flush=True)
                continue
            if len(proposed) > 2 or any(p not in WRITABLE for p in proposed):
                raise ValueError("Model attempted edits outside production allowlist")
            for path, value in proposed.items():
                if not isinstance(value, str) or len(value) > 120_000:
                    raise ValueError("Invalid replacement")
                compile(value, path, "exec")
                (ROOT / path).write_text(value, encoding="utf-8")
            after, log = run_tests()
            if after != 0:
                feedback = log[-4500:]
                print("Targeted tests failed; requesting corrected patch", flush=True)
                continue
            full_result, full_log = run_tests(full_suite=True)
            if full_result != 0:
                print("FULL SUITE DETAILS:", full_log[-3500:], flush=True)
                feedback = full_log[-4500:]
                print("Full test suite failed; requesting corrected patch", flush=True)
                continue
            succeeded = True
            print("PASS: repaired sandbox passes targeted and full test suites", flush=True)
            return 0
        print("Repair not validated after two attempts", flush=True)
        return 1
    except Exception as exc:
        print("Repair blocked: " + str(exc), flush=True)
        return 1
    finally:
        if not succeeded:
            for p, original in originals.items():
                (ROOT / p).write_text(original, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
