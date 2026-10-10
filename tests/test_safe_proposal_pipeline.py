"""Regression tests for read-only local AI proposal + hosted-only validation."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace


WRITABLE = (
    "src/rg_youtube_control/seo_quality_gate.py",
    "src/rg_youtube_control/rejected_seo.py",
)
NEEDLE = 'return hashlib.sha256(raw.encode("utf-8")).hexdigest()'


def _modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return (
        importlib.import_module("rg_youtube_proposal_only"),
        importlib.import_module("rg_youtube_validate_proposal"),
    )


def _fixture(tmp_path):
    for file in WRITABLE:
        (tmp_path / file).parent.mkdir(parents=True, exist_ok=True)
    gate = "def gate():\n    return True\n"
    rejected = "import hashlib\ndef f(raw):\n    " + NEEDLE + "\n"
    (tmp_path / WRITABLE[0]).write_text(gate, encoding="utf-8")
    (tmp_path / WRITABLE[1]).write_text(rejected, encoding="utf-8")
    return {WRITABLE[0]: gate, WRITABLE[1]: rejected}


def test_readonly_proposal_does_not_execute_or_write_model_code(tmp_path, monkeypatch):
    proposal, _ = _modules(monkeypatch)
    original = _fixture(tmp_path)
    monkeypatch.setattr(proposal, "ROOT", tmp_path)
    monkeypatch.setattr(proposal, "OUTPUT", tmp_path / "rg_youtube_proposed_candidate.json")
    monkeypatch.setattr(proposal, "WRITABLE", WRITABLE)
    monkeypatch.setattr(proposal, "run_tests", lambda **kwargs: (1, "fingerprint mismatch"))
    # Deliberately invalid at import/runtime but valid to compile: MUST never execute.
    candidate = "raise RuntimeError('MODEL CODE EXECUTED ON ALEXPC')\n"
    monkeypatch.setattr(proposal, "ask_model", lambda *args: {"files": {WRITABLE[1]: candidate}})
    assert proposal.propose() == 0
    result = json.loads(proposal.OUTPUT.read_text(encoding="utf-8"))
    assert result["status"] == "PROPOSED_UNVERIFIED"
    assert result["files"][WRITABLE[1]] == candidate
    for path, text in original.items():
        assert (tmp_path / path).read_text(encoding="utf-8") == text


def test_synthetic_drill_restores_original_source_after_proposal(tmp_path, monkeypatch):
    proposal, _ = _modules(monkeypatch)
    original = _fixture(tmp_path)
    monkeypatch.setattr(proposal, "ROOT", tmp_path)
    monkeypatch.setattr(proposal, "OUTPUT", tmp_path / "rg_youtube_proposed_candidate.json")
    monkeypatch.setattr(proposal, "WRITABLE", WRITABLE)
    monkeypatch.setattr(proposal, "run_tests", lambda **kwargs: (1, "fingerprint mismatch"))
    monkeypatch.setattr(proposal, "ask_model", lambda *args: {"files": {WRITABLE[1]: original[WRITABLE[1]]}})
    assert proposal.propose(drill=True) == 0
    assert (tmp_path / WRITABLE[1]).read_text(encoding="utf-8") == original[WRITABLE[1]]
    assert json.loads(proposal.OUTPUT.read_text(encoding="utf-8"))["drill"] is True


def test_green_project_never_calls_ollama(tmp_path, monkeypatch):
    proposal, _ = _modules(monkeypatch)
    _fixture(tmp_path)
    monkeypatch.setattr(proposal, "ROOT", tmp_path)
    monkeypatch.setattr(proposal, "OUTPUT", tmp_path / "rg_youtube_proposed_candidate.json")
    monkeypatch.setattr(proposal, "WRITABLE", WRITABLE)
    monkeypatch.setattr(proposal, "run_tests", lambda **kwargs: (0, "all tests pass"))
    monkeypatch.setattr(proposal, "ask_model", lambda *args: (_ for _ in ()).throw(AssertionError("Ollama should not be called")))
    assert proposal.propose() == 0
    assert json.loads(proposal.OUTPUT.read_text(encoding="utf-8"))["status"] == "NO_CHANGE"


def test_hosted_validator_rejects_wrong_checkout_hash(tmp_path, monkeypatch):
    _, validator = _modules(monkeypatch)
    original = _fixture(tmp_path)
    monkeypatch.setattr(validator, "ROOT", tmp_path)
    monkeypatch.setattr(validator, "CANDIDATE", tmp_path / "rg_youtube_proposed_candidate.json")
    monkeypatch.setattr(validator, "REPORT", tmp_path / "rg_youtube_hosted_validation.json")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    payload = {
        "schema": "RG_YOUTUBE_PROPOSAL_V1", "status": "PROPOSED_UNVERIFIED",
        "drill": False, "base_sha256": {p: "0" * 64 for p in WRITABLE},
        "files": {WRITABLE[1]: "print('unsafe candidate')\n"},
    }
    validator.CANDIDATE.write_text(json.dumps(payload), encoding="utf-8")
    assert validator.main() == 2
    assert json.loads(validator.REPORT.read_text())["status"] == "BLOCKED"
    assert (tmp_path / WRITABLE[1]).read_text(encoding="utf-8") == original[WRITABLE[1]]


def test_hosted_validator_does_not_execute_model_on_selfhosted(tmp_path, monkeypatch):
    _, validator = _modules(monkeypatch)
    monkeypatch.setattr(validator, "REPORT", tmp_path / "rg_youtube_hosted_validation.json")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "self-hosted")
    assert validator.main() == 2
    assert not validator.REPORT.exists()


def test_hosted_review_patch_survives_until_artifact_creation(tmp_path, monkeypatch):
    _, validator = _modules(monkeypatch)
    original = _fixture(tmp_path)
    monkeypatch.setattr(validator, "ROOT", tmp_path)
    monkeypatch.setattr(validator, "CANDIDATE", tmp_path / "rg_youtube_proposed_candidate.json")
    monkeypatch.setattr(validator, "REPORT", tmp_path / "rg_youtube_hosted_validation.json")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    changed = original[WRITABLE[1]] + "# reviewed patch\n"
    candidate = {
        "schema": "RG_YOUTUBE_PROPOSAL_V1",
        "status": "PROPOSED_UNVERIFIED",
        "drill": False,
        "base_sha256": {p: hashlib.sha256(text.encode()).hexdigest() for p, text in original.items()},
        "files": {WRITABLE[1]: changed},
    }
    validator.CANDIDATE.write_text(json.dumps(candidate), encoding="utf-8")
    monkeypatch.setattr(
        validator.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="all passed", stderr=""),
    )
    assert validator.main() == 0
    assert (tmp_path / WRITABLE[1]).read_text(encoding="utf-8") == changed
    assert json.loads(validator.REPORT.read_text())["status"] == "VALIDATED_FOR_REVIEW"


def test_hosted_drill_restores_source_after_verification(tmp_path, monkeypatch):
    _, validator = _modules(monkeypatch)
    original = _fixture(tmp_path)
    monkeypatch.setattr(validator, "ROOT", tmp_path)
    monkeypatch.setattr(validator, "CANDIDATE", tmp_path / "rg_youtube_proposed_candidate.json")
    monkeypatch.setattr(validator, "REPORT", tmp_path / "rg_youtube_hosted_validation.json")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    candidate = {
        "schema": "RG_YOUTUBE_PROPOSAL_V1",
        "status": "PROPOSED_UNVERIFIED",
        "drill": True,
        "base_sha256": {p: hashlib.sha256(text.encode()).hexdigest() for p, text in original.items()},
        "files": {WRITABLE[1]: original[WRITABLE[1]]},
    }
    validator.CANDIDATE.write_text(json.dumps(candidate), encoding="utf-8")
    monkeypatch.setattr(
        validator.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="319 passed", stderr=""),
    )
    assert validator.main() == 0
    assert json.loads(validator.REPORT.read_text())["status"] == "DRILL_PASS"
    for name, source in original.items():
        assert (tmp_path / name).read_text(encoding="utf-8") == source
