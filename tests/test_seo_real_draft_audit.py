import json
import sqlite3
from rg_youtube_control.seo_real_draft_audit import run


def test_existing_drafts_are_audited_read_only(tmp_path):
    database = tmp_path / "test.sqlite"
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE videos(video_id TEXT PRIMARY KEY, profile TEXT, title TEXT);
            CREATE TABLE optimization_drafts(video_id TEXT, title TEXT, description TEXT, tags_json TEXT);
            INSERT INTO videos VALUES('MEitKm687xo', 'main', 'Криза');
            INSERT INTO optimization_drafts VALUES('MEitKm687xo', 'Криза', 'паливна криза', '[]');
        """)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "MEitKm687xo.json").write_text(json.dumps({
        "schema": "RG_VIDEO_SEO_EVIDENCE_V1", "video_id": "MEitKm687xo",
        "transcript_sha256": "a" * 64,
        "blocks": [{"topics": [{"topic": "паливна криза", "evidence": "паливна криза"}]}]
    }), encoding="utf-8")
    before = database.read_bytes()
    report = run(database, evidence)
    assert report["inspected"] == 1
    assert report["audited"] == 1
    assert report["audit"]["ready"] == 0  # do not invent the other 2 titles
    assert report["audit"]["items"][0]["issues"] == ("exactly_three_distinct_titles_required",)
    assert database.read_bytes() == before


def test_missing_evidence_skips_without_generating_claims(tmp_path):
    database = tmp_path / "test.sqlite"
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE videos(video_id TEXT PRIMARY KEY, profile TEXT, title TEXT);
            CREATE TABLE optimization_drafts(video_id TEXT, title TEXT, description TEXT, tags_json TEXT);
            INSERT INTO videos VALUES('MEitKm687xo', 'live', 'Title');
            INSERT INTO optimization_drafts VALUES('MEitKm687xo', 'Title', 'Desc', '[]');
        """)
    evidence = tmp_path / "empty"
    evidence.mkdir()
    report = run(database, evidence)
    assert report["audited"] == 0
    assert report["skipped"][0]["reason"] == "verified_evidence_missing"
