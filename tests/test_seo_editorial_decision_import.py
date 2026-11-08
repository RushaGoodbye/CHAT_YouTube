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


def test_browser_numbered_export_latest_selected_by_mtime(tmp_path):
    import os
    from rg_youtube_control.seo_editorial_decision_import import latest_decisions_export
    first=tmp_path/"RG_G2_HUMAN_DECISIONS.json"
    later=tmp_path/"RG_G2_HUMAN_DECISIONS (1).json"
    first.write_text("old",encoding="utf-8")
    later.write_text("new",encoding="utf-8")
    os.utime(first,ns=(100000000000,100000000000))
    os.utime(later,ns=(200000000000,200000000000))
    assert latest_decisions_export(tmp_path)==later


def test_never_fallback_to_stale_export_on_invalid_latest(tmp_path):
    import os
    from rg_youtube_control.seo_editorial_decision_import import import_latest_review_decisions
    a,b,dest=make_files(tmp_path)
    downloads=tmp_path/"downloads"
    downloads.mkdir()
    valid=downloads/"RG_G2_HUMAN_DECISIONS.json"
    invalid=downloads/"RG_G2_HUMAN_DECISIONS (1).json"
    valid.write_bytes(b.read_bytes())
    invalid.write_text('{"schema":"WRONG"}',encoding="utf-8")
    os.utime(valid,ns=(100000000000,100000000000))
    os.utime(invalid,ns=(200000000000,200000000000))
    with pytest.raises(ValueError,match="INVALID_DECISION_SCHEMA"):
        import_latest_review_decisions(handoff_file=a,downloads=downloads,output_dir=tmp_path)
    assert not any(tmp_path.glob("G2_EDITORIAL_VALIDATED_*.json"))


def test_latest_export_preserves_validated_history(tmp_path):
    import os
    from rg_youtube_control.seo_editorial_decision_import import import_latest_review_decisions
    a,b,dest=make_files(tmp_path)
    downloads=tmp_path/"downloads"
    downloads.mkdir()
    one=downloads/"RG_G2_HUMAN_DECISIONS.json"
    one.write_bytes(b.read_bytes())
    os.utime(one,ns=(100000000000,100000000000))
    src,out,result=import_latest_review_decisions(
        handoff_file=a,downloads=downloads,output_dir=tmp_path)
    assert src==one and out.exists()
    with pytest.raises(FileExistsError):
        import_latest_review_decisions(handoff_file=a,downloads=downloads,output_dir=tmp_path)
    two=downloads/"RG_G2_HUMAN_DECISIONS (1).json"
    two.write_bytes(b.read_bytes())
    os.utime(two,ns=(200000000000,200000000000))
    src2,out2,result2=import_latest_review_decisions(
        handoff_file=a,downloads=downloads,output_dir=tmp_path)
    assert src2==two and out2!=out and out.exists()
    assert result["publication_allowed"] is False and result2["g2_accepted"] is False


def test_ambiguous_modification_time_does_not_guess(tmp_path):
    import os
    from rg_youtube_control.seo_editorial_decision_import import latest_decisions_export
    a=tmp_path/"RG_G2_HUMAN_DECISIONS.json"
    b=tmp_path/"RG_G2_HUMAN_DECISIONS (1).json"
    a.write_text("first")
    b.write_text("second")
    for p in (a,b):os.utime(p,ns=(100000000000,100000000000))
    with pytest.raises(ValueError,match="AMBIGUOUS_LATEST_EXPORT"):
        latest_decisions_export(tmp_path)


def test_export_filename_filter_ignores_unrelated_json(tmp_path):
    from rg_youtube_control.seo_editorial_decision_import import latest_decisions_export
    (tmp_path/"PRIVATE_UNRELATED.json").write_text("bad")
    (tmp_path/"RG_G2_HUMAN_DECISIONS.json.bak").write_text("bad")
    with pytest.raises(ValueError,match="NO_EDITORIAL_DECISION_EXPORT"):
        latest_decisions_export(tmp_path)
