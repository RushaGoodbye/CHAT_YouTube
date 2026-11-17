from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from rg_youtube_control.batch_seo_pipeline import inspect_srt, run_batch, srt_text


def _db(path: Path):
    db=sqlite3.connect(path)
    db.executescript("""
      CREATE TABLE videos(video_id TEXT,title TEXT,duration TEXT,views INTEGER,profile TEXT);
      CREATE TABLE optimization_drafts(video_id TEXT,status TEXT,generation TEXT,quality_state TEXT,title_variants_json TEXT);
      INSERT INTO videos VALUES ('abcdefghijk','Example','PT2M0S',100,'main');
      INSERT INTO optimization_drafts VALUES ('abcdefghijk','ready','legacy','','[]');
    """)
    db.commit()
    db.close()


def test_srt_roundtrip_and_truncation():
    rows=[{"text":"Something meaningful happened during the dialogue and is captured correctly",
           "start":i*10,"duration":9} for i in range(12)]
    text=srt_text(rows)
    result=inspect_srt(text,120)
    assert result["complete"]
    assert result["segments"]==12
    assert not inspect_srt(text,900)["complete"]


def test_batch_dry_run_does_not_touch_db_or_srt(tmp_path):
    db=tmp_path/"db.sqlite"
    path=tmp_path/"transcripts"
    path.mkdir()
    _db(db)
    before=db.read_bytes()
    result=run_batch(db_path=db,srt_dir=path,profile="main",limit=10,acquire=False)
    assert result["status_counts"]=={"missing_dry_run":1}
    assert result["editorial_approval_automated"] is False
    assert result["youtube_data_api_units_used"]==0
    assert result["youtube_metadata_modified"] is False
    assert db.read_bytes()==before
    assert not (path/"abcdefghijk.srt").exists()
    assert Path(result["report_csv"]).exists()


def test_batch_skips_valid_existing_and_preserves_it(tmp_path):
    db=tmp_path/"db.sqlite"
    path=tmp_path/"transcripts"
    path.mkdir()
    _db(db)
    content=srt_text([{"text":"A distinct substantive passage appears here in a dialogue","start":i*10,
                       "duration":9} for i in range(12)])
    srt=path/"abcdefghijk.srt"
    srt.write_text(content,encoding="utf-8")
    result=run_batch(db_path=db,srt_dir=path,profile="main",limit=10,acquire=True)
    assert result["pending_count"]==0
    assert srt.read_text(encoding="utf-8")==content


def test_incomplete_existing_is_never_overwritten(tmp_path):
    db=tmp_path/"db.sqlite"
    path=tmp_path/"transcripts"
    path.mkdir()
    _db(db)
    srt=path/"abcdefghijk.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n",encoding="utf-8")
    result=run_batch(db_path=db,srt_dir=path,profile="main",limit=10,acquire=False)
    assert result["status_counts"]=={"incomplete":1}
    assert srt.read_text(encoding="utf-8").endswith("hello\n")
