"""Read-only Ollama patch proposal generator for RG YouTube Control.

No LLM-produced source file is written, imported, or executed on AlexPC.
The ONLY output is a JSON candidate consumed on a disposable hosted runner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from rg_youtube_seo_repair_agent import ROOT, WRITABLE, ask_model, run_tests

OUTPUT = ROOT / "rg_youtube_proposed_candidate.json"


def propose(*, drill: bool = False) -> int:
    # Synthetic drill uses a deterministic, trusted defect and MUST restore checkout.
    target = ROOT / "src/rg_youtube_control/rejected_seo.py"
    original = target.read_text(encoding="utf-8")
    needle = 'return hashlib.sha256(raw.encode("utf-8")).hexdigest()'
    replacement = 'return "broken-fingerprint"'
    if drill and original.count(needle) != 1:
        raise RuntimeError("Synthetic fingerprint drill invariant changed")

    baseline = {p: (ROOT / p).read_text(encoding="utf-8") for p in WRITABLE}
    result = {
        "schema": "RG_YOUTUBE_PROPOSAL_V1",
        "status": "NOT_VALIDATED",
        "drill": drill,
        "base_sha256": {
            p: hashlib.sha256(source.encode("utf-8")).hexdigest()
            for p, source in baseline.items()
        },
        "files": {},
    }
    try:
        if drill:
            target.write_text(original.replace(needle, replacement), encoding="utf-8")
        targeted, failures = run_tests()
        full, full_log = run_tests(full_suite=True)
        print("BASELINE:", "targeted=", targeted, "full=", full, flush=True)
        if full != 0 and any(
            token in full_log
            for token in ("ERROR collecting", "ModuleNotFoundError", "ImportError while importing")
        ):
            raise RuntimeError("Test collection or dependency failure; no AI proposal allowed")
        if targeted == 0:
            if full != 0:
                raise RuntimeError("Full-suite failure outside allowlisted SEO repair scope")
            result["status"] = "NO_CHANGE"
            return 0
        # Generate once; NEVER execute the response on the local machine.
        proposed = ask_model(failures).get("files", {})
        if not isinstance(proposed, dict) or not proposed:
            raise RuntimeError("Ollama produced no repair candidate")
        if len(proposed) > 2 or any(p not in WRITABLE for p in proposed):
            raise RuntimeError("Model requested a file outside the strict allowlist")
        for path, content in proposed.items():
            if not isinstance(content, str) or len(content) > 120_000:
                raise RuntimeError("Invalid model source payload")
            compile(content, path, "exec")  # parse/compile only; DO NOT run it.
        result["files"] = proposed
        result["status"] = "PROPOSED_UNVERIFIED"
        print("PROPOSAL ONLY:", ", ".join(proposed), flush=True)
        return 0
    except Exception as exc:
        result["status"] = "BLOCKED"
        result["error"] = str(exc)[:1000]
        print("PROPOSAL BLOCKED:", result["error"], flush=True)
        return 2
    finally:
        if drill:
            target.write_text(original, encoding="utf-8")
        OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drill", action="store_true", help="Inject trusted fingerprint defect, then restore")
    args = parser.parse_args()
    return propose(drill=args.drill)


if __name__ == "__main__":
    raise SystemExit(main())
