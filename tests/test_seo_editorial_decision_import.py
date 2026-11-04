import json
from pathlib import Path

import pytest

from rg_youtube_control.seo_editorial_decisions import (
    create_review_manifest, DECISIONS_SCHEMA,
)
from rg_youtube_control.seo_editorial_decision_import import import_review_decisions


def make_files(tmp_path: Path):
    source = {
        "records": [{
            "video_id": "AbCdEfGh123",
            "record_id": 1,
            "source_quote": "This is an exact source quotation recorded in the original captions.",
            "initial_topic": "Тема з джерела",
            "initial_summary": "Співрозмовник говорить про підтверджену оригіналом тему.",
            "status": "SOURCE_QUOTED_AI_RISK",
        }]
    }
    manifest = create_review_manifest(source)
    submission = {
        "schema": DECISIONS_SCHEMA,
        "manifest_sha256": manifest["manifest_sha256"],
        "reviewer": "editor-1",
        "decisions": [{
            **manifest["cards"][0],
            "decision": "approve",
            "corrected_topic": "",
            "corrected_summary": "",
            "note": "",
        }],
    }
    a, b, dest = [tmp_path / x for x in
                  ("handoff.json", "decisions.json", "validated.json")]
    a.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    b.write_text(json.dumps(submission, ensure_ascii=False), encoding="utf-8")
    return a, b, dest


def test_import_creates_separate_nonpublishing_report(tmp_path):
    a, b, dest = make_files(tmp_path)
    result = import_review_decisions(
        handoff_file=a, decisions_file=b, output_file=dest,
    )
    assert dest.exists() and result["reviewed"] == 1
    assert result["g2_accepted"] is False
    assert result["publication_allowed"] is False
    assert json.loads(dest.read_text(encoding="utf-8")) == result


def test_import_does_not_overwrite_source(tmp_path):
    a, b, dest = make_files(tmp_path)
    with pytest.raises(ValueError, match="OUTPUT_CANNOT_OVERWRITE"):
        import_review_decisions(handoff_file=a, decisions_file=b, output_file=a)
    assert not dest.exists()


def test_tampered_submission_does_not_create_output(tmp_path):
    a, b, dest = make_files(tmp_path)
    submission = json.loads(b.read_text(encoding="utf-8"))
    submission["decisions"][0]["source_quote_sha256"] = "a" * 64
    b.write_text(json.dumps(submission), encoding="utf-8")
    with pytest.raises(ValueError, match="DECISION_SOURCE_CHANGED"):
        import_review_decisions(handoff_file=a, decisions_file=b, output_file=dest)
    assert not dest.exists()
