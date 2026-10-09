"""Regression checks for safe autonomous repair workflow."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/rg-youtube-autonomous-repair.yml"
AGENT = ROOT / "scripts/rg_youtube_seo_repair_agent.py"


def test_agent_cannot_write_tests_and_requires_full_suite():
    source = AGENT.read_text(encoding="utf-8")
    assert "any(p not in WRITABLE for p in proposed)" in source
    assert "run_tests(full_suite=True)" in source
    # Rollback after any failed attempt, even if both attempts fail.
    assert "finally:" in source
    assert "if not succeeded:" in source
    assert '(ROOT / p).write_text(original, encoding="utf-8")' in source
    assert "succeeded = True" in source
    assert "RG_REPAIR_ALLOWED_ROOT" in source
    assert "marker.is_file()" in source
    assert 'parser.add_argument("--apply", action="store_true"' in source


def test_workflow_read_only_no_scheduled_or_unreviewed_push():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "contents: read" in source
    assert "contents: write" not in source
    assert "schedule:" not in source
    assert "workflow_dispatch:" in source
    assert "gh pr create" not in source
    assert "git push" not in source
    assert "rg_youtube_proposed_repair.patch" in source
    assert "runs-on: [self-hosted, rg, alexpc, windows]" in source
    assert "python -m venv .venv" in source
    assert r".venv\Scripts\python.exe" in source
    assert "if: inputs.drill == true" in source
    assert "rg_youtube_ollama_drill_result.json" in source
    assert "Baseline test collection or infrastructure error" in source
    assert "Repair step failed: no validated patch" in source

def test_apply_rejected_without_explicit_sandbox_even_with_root_env():
    env = {**os.environ, "RG_REPAIR_ALLOWED_ROOT": str(ROOT)}
    proc = subprocess.run(
        [sys.executable, str(AGENT), "--apply"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "BLOCKED: --apply requires an explicitly authorized sandbox" in proc.stdout
