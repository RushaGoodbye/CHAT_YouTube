"""Generate unexecuted local Ollama patch proposals.

Model-generated code is never written or executed on AlexPC. In drill mode,
the artificial bug is inserted ONLY into a disposable copy of the checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import rg_youtube_seo_repair_agent as agent
from rg_youtube_seo_repair_agent import ROOT, WRITABLE, ask_model, run_tests

OUTPUT = ROOT / "rg_youtube_proposed_candidate.json"
NEEDLE = 'return hashlib.sha256(raw.encode("utf-8")).hexdigest()'


def _propose(test_root: Path, *, drill: bool) -> int:
    originals = {p: (ROOT / p).read_text(encoding="utf-8") for p in WRITABLE}
    result = {
        "schema": "RG_YOUTUBE_PROPOSAL_V1",
        "status": "NOT_VALIDATED",
        "drill": drill,
        "base_sha256": {
            p: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for p, content in originals.items()
        },
        "files": {},
    }
    previous_root = agent.ROOT
    try:
        # The imported agent uses its module ROOT for read-only test/source access.
        agent.ROOT = test_root
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

        # Generate only a JSON document. Never write/import/run Ollama source.
        proposed = ask_model(failures).get("files", {})
        if not isinstance(proposed, dict) or not proposed:
            raise RuntimeError("Ollama produced no repair candidate")
        if len(proposed) > 2 or any(p not in WRITABLE for p in proposed):
            raise RuntimeError("Model requested a file outside the strict allowlist")
        for path, content in proposed.items():
            if not isinstance(content, str) or len(content) > 120_000:
                raise RuntimeError("Invalid model source payload")
            compile(content, path, "exec")  # parse only; DO NOT execute
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
        agent.ROOT = previous_root
        OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def propose(*, drill: bool = False) -> int:
    if not drill:
        return _propose(ROOT, drill=False)
    original = (ROOT / "src/rg_youtube_control/rejected_seo.py").read_text(encoding="utf-8")
    if original.count(NEEDLE) != 1:
        raise RuntimeError("Synthetic fingerprint drill invariant changed")
    # No modification to real checkout, even temporarily.
    with tempfile.TemporaryDirectory(prefix="RG_YOUTUBE_PROPOSAL_") as folder:
        sandbox = Path(folder) / "checkout"
        shutil.copytree(
            ROOT, sandbox,
            ignore=shutil.ignore_patterns(
                ".git", ".venv", "venv", "__pycache__", ".pytest_cache", "*.pyc",
                "rg_youtube_proposed_candidate.json",
            ),
        )
        target = sandbox / "src/rg_youtube_control/rejected_seo.py"
        target.write_text(original.replace(NEEDLE, 'return "broken-fingerprint"'), encoding="utf-8")
        print("ISOLATED DRILL:", sandbox, flush=True)
        return _propose(sandbox, drill=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drill", action="store_true", help="Diagnose artificial defect in a disposable copy")
    return propose(drill=parser.parse_args().drill)


if __name__ == "__main__":
    raise SystemExit(main())
