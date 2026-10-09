"""Regression checks for safe autonomous repair workflow."""
from pathlib import Path

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
