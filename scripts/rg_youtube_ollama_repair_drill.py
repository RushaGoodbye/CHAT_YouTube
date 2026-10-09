"""One-shot isolated repair drill. Never touches the source checkout."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

def main():
    source = Path.cwd().resolve()
    expected = source / "scripts" / "rg_youtube_seo_repair_agent.py"
    if not expected.is_file():
        raise SystemExit("Run from the extracted PR #86 repository folder")
    with tempfile.TemporaryDirectory(prefix="RG_YOUTUBE_AUTOFIX_DRILL_") as tmp:
        sandbox = Path(tmp) / "checkout"
        shutil.copytree(source, sandbox, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc"))
        target = sandbox / "src/rg_youtube_control/rejected_seo.py"
        original = target.read_text(encoding="utf-8")
        source_target = source / "src/rg_youtube_control/rejected_seo.py"
        needle = 'return hashlib.sha256(raw.encode("utf-8")).hexdigest()'
        if original.count(needle) != 1:
            raise SystemExit("Expected fingerprint implementation has changed; drill stopped")
        target.write_text(original.replace(needle, 'return "broken-fingerprint"'), encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(sandbox / "src")}
        print("SANDBOX:", sandbox, flush=True)
        print("TEST ERROR: deliberately broken fingerprints (sandbox only)", flush=True)
        trial = subprocess.run(
            [sys.executable, "scripts/rg_youtube_seo_repair_agent.py", "--apply"],
            cwd=sandbox, env=env, text=True, capture_output=True, timeout=900,
        )
        print(trial.stdout[-6500:], flush=True)
        if trial.stderr:
            print(trial.stderr[-2500:], flush=True)
        fixed = target.read_text(encoding="utf-8")
        repaired = trial.returncode == 0 and fixed != original.replace(needle, 'return "broken-fingerprint"') and source_target.read_text(encoding="utf-8") == original
        result = {
            "drill": "rg_youtube_ollama_repair_v1",
            "status": "PASS" if repaired else "NOT_PASSED",
            "agent_exit_code": trial.returncode,
            "source_checkout_unchanged": source_target.read_text(encoding="utf-8") == original,
            "sandbox_repaired": repaired,
        }
        report = source / "rg_youtube_ollama_drill_result.json"
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0 if repaired else 1

if __name__ == "__main__":
    raise SystemExit(main())
