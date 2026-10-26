#!/usr/bin/env python3
"""Operator-authorized, one-shot RG NEWS2 archive of old photo queue entries.

Pins archive eligibility to 1353 candidate IDs from the already existing NAS
backup taken 2026-10-26T10:37:49Z. Keeps all rows/foreign references/audit
and Telegram receipts; changes ONLY candidates.status to archived_stale
for still-unreviewed, unsent, old awaiting_photo_review records.

No Telegram requests, second poller, public posts, scheduler edits, or worker
execution. An online backup is saved BEFORE any production update; mutations
are a single SQLite transaction and are verified before commit. Python 3.8+.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import time

ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
VAULT=pathlib.Path("/volume1/docker/RG_NAS_MONITOR/news2_private_photo_snapshots")
BASELINE=VAULT/"batch-prep-20261026T103749Z"/"news.sqlite3"
EXPECTED=1353
FROM="awaiting_photo_review"
TO="archived_stale"
UTC=dt.timezone.utc
PRESERVE=("rg_news2_photo_dispatch","moderation_dispatch","rg_v35_photo_audit")
COLUMNS=("id","status","photo_reviewed","telegram_message_id","photo_review_note")

def read_conn(path):
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("BACKUP_OR_LIVE_DB_MISSING")
    return sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=8)

def schema(conn):
    return {r[1] for r in conn.execute('PRAGMA table_info("candidates")')}

def validate_baseline(path,expected):
    db=read_conn(path)
    try:
        if not set(COLUMNS).issubset(schema(db)):
            raise RuntimeError("BASELINE_COLUMNS_DIFFER")
        ids=[r[0] for r in db.execute(
            "SELECT id FROM candidates WHERE status=?",(FROM,))]
        if len(ids)!=expected or len(set(ids))!=len(ids) or any(x is None for x in ids):
            raise RuntimeError("BASELINE_COUNT_OR_IDENTIFIERS_CHANGED")
        if not 1<=len(ids)<=2000:
            raise RuntimeError("OVER_SAFETY_LIMIT")
        return ids,schema(db)
    finally:db.close()

def counts(conn):
    tab={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "candidates" not in tab or not set(PRESERVE).issubset(tab):
        raise RuntimeError("DEPENDENT_TABLE_MISSING")
    result={t:conn.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0] for t in PRESERVE}
    result["receipt_count"]=conn.execute(
        "SELECT COUNT(*) FROM rg_news2_photo_dispatch WHERE telegram_message_id IS NOT NULL"
    ).fetchone()[0]
    return result

def eligibility():
    return ("id IN (SELECT id FROM rg_news2_archive_ids) "
            "AND status=? "
            "AND (photo_reviewed IS NULL OR photo_reviewed=0) "
            "AND telegram_message_id IS NULL "
            "AND (photo_review_note IS NULL OR TRIM(photo_review_note)='')")

def stage(conn,ids):
    conn.execute("CREATE TEMP TABLE rg_news2_archive_ids(id PRIMARY KEY)")
    conn.executemany("INSERT INTO rg_news2_archive_ids (id) VALUES (?)",
                     ((v,) for v in ids))

def preflight(conn,expected_schema):
    if schema(conn)!=expected_schema or not set(COLUMNS).issubset(schema(conn)):
        raise RuntimeError("LIVE_SCHEMA_CHANGED")
    triggers=conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='trigger' AND tbl_name='candidates'"
    ).fetchone()[0]
    if triggers:
        raise RuntimeError("CANDIDATE_TRIGGERS_NEED_REVIEW")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise RuntimeError("PREEXISTING_FOREIGN_KEY_ERRORS")
    return counts(conn)

def backup_now(live,vault):
    if vault.is_symlink() or not vault.is_dir():
        raise RuntimeError("BACKUP_DIRECTORY_UNAVAILABLE")
    # Dedicated directory with owner-only permissions. Do not change Gatus.
    folder=vault/("status-archive-"+dt.datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    folder.mkdir(mode=0o700)
    dest=folder/"before.sqlite3"
    source=read_conn(live)
    target=sqlite3.connect(str(dest),timeout=8)
    try:
        source.backup(target,pages=256,sleep=0.05)
    finally:
        target.close()
        source.close()
    os.chmod(str(dest),0o600)
    return folder,dest

def trial_update(snapshot,ids,expected_schema):
    conn=sqlite3.connect(str(snapshot),timeout=8,isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        preflight(conn,expected_schema)
        stage(conn,ids)
        row=conn.execute(
            "SELECT id FROM candidates WHERE "+eligibility()+" LIMIT 1",(FROM,)
        ).fetchone()
        if row:
            conn.execute("UPDATE candidates SET status=? WHERE id=? AND "+eligibility(),
                         (TO,row[0],FROM))
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("SHADOW_FOREIGN_KEY_ERROR")
        conn.execute("ROLLBACK")
    finally:
        conn.close()

def apply(root=ROOT,vault=VAULT,baseline=BASELINE,expected=EXPECTED):
    if hasattr(os,"geteuid") and os.geteuid()!=0:
        raise RuntimeError("ROOT_REQUIRED")
    live=root/"news.sqlite3"
    if not live.is_file() or live.is_symlink() or live.parent.resolve()!=root.resolve():
        raise RuntimeError("LIVE_DB_PATH_INVALID")
    ids,expected_schema=validate_baseline(baseline,expected)
    folder,backup=backup_now(live,vault)
    # Verify update is accepted by this exact database schema, but never
    # commit the trial update on the backup.
    trial_update(backup,ids,expected_schema)
    conn=sqlite3.connect(str(live),timeout=10,isolation_level=None)
    applied=False
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("BEGIN IMMEDIATE")
        before=preflight(conn,expected_schema)
        stage(conn,ids)
        source_count=conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE "+eligibility(),(FROM,)
        ).fetchone()[0]
        if source_count>expected:
            raise RuntimeError("ELIGIBLE_COUNT_UNEXPECTED")
        # Capture only IDs of the rows really changed, in a private vault file.
        changed=[r[0] for r in conn.execute(
            "SELECT id FROM candidates WHERE "+eligibility(),(FROM,))]
        if len(changed)!=source_count:
            raise RuntimeError("CANDIDATE_COUNT_MISMATCH")
        changed_result=conn.execute(
            "UPDATE candidates SET status=? WHERE "+eligibility(),
            (TO,FROM)
        ).rowcount
        if changed_result!=source_count:
            raise RuntimeError("UPDATE_COUNT_MISMATCH")
        if conn.execute("SELECT COUNT(*) FROM candidates WHERE "+eligibility(),(FROM,)).fetchone()[0]:
            raise RuntimeError("ELIGIBLE_ROWS_REMAIN")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("FOREIGN_KEY_VIOLATION")
        after=counts(conn)
        if before!=after:
            raise RuntimeError("MODERATION_LEDGER_OR_RECEIPT_COUNT_CHANGED")
        quick=conn.execute("PRAGMA quick_check(1)").fetchone()[0]
        if quick!="ok":
            raise RuntimeError("SQLITE_INTEGRITY_NOT_OK")
        remaining=conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE status=?",(FROM,)
        ).fetchone()[0]
        total=conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        archive_file=folder/"archived_ids.json"
        archive_file.write_text(json.dumps(changed,ensure_ascii=False))
        os.chmod(str(archive_file),0o600)
        conn.execute("COMMIT")
        applied=True
        result={
            "schema":"RG_NEWS2_OLD_PHOTO_QUEUE_ARCHIVE_V1",
            "status":"COMMITTED",
            "baseline_candidates":len(ids),
            "archived_old_unreviewed_count":changed_result,
            "still_awaiting_photo_review":remaining,
            "total_candidates_preserved":total,
            "new_candidates_untouched":True,
            "all_referenced_candidates_preserved":True,
            "moderation_ledgers_unchanged":True,
            "telegram_receipts_unchanged":True,
            "sqlite_integrity":"ok",
            "backup":str(backup),
            "archived_row_id_manifest":str(archive_file),
            "bot_api_calls":0,
            "public_channel_posts":0,
            "second_pollers_started":0,
            "scheduler_changes":0
        }
        summary=folder/"result.json"
        summary.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
        os.chmod(str(summary),0o600)
        return result
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()

def selftest():
    with tempfile.TemporaryDirectory() as temp:
        base=pathlib.Path(temp)
        root=base/"live";root.mkdir()
        vault=base/"vault";vault.mkdir(mode=0o700)
        live=root/"news.sqlite3"
        db=sqlite3.connect(str(live))
        db.execute("CREATE TABLE candidates(id TEXT PRIMARY KEY,status TEXT,photo_reviewed INT,telegram_message_id INT,photo_review_note TEXT)")
        db.executemany("INSERT INTO candidates VALUES (?,'awaiting_photo_review',0,NULL,'')",
                       (("old%04d"%i,) for i in range(EXPECTED)))
        db.execute("CREATE TABLE rg_news2_photo_dispatch(candidate_id TEXT,telegram_message_id INT)")
        db.execute("CREATE TABLE moderation_dispatch(state TEXT)")
        db.execute("CREATE TABLE rg_v35_photo_audit(outcome TEXT)")
        db.execute("INSERT INTO rg_news2_photo_dispatch VALUES ('old0001',123)")
        db.commit()
        baseline=vault/"baseline.sqlite3"
        snapshot=sqlite3.connect(str(baseline));db.backup(snapshot);snapshot.close()
        db.execute("INSERT INTO candidates VALUES ('new','awaiting_photo_review',0,NULL,'')")
        db.execute("UPDATE candidates SET photo_reviewed=1 WHERE id='old0002'")
        db.execute("UPDATE candidates SET telegram_message_id=456 WHERE id='old0003'")
        db.commit();db.close()
        if not hasattr(os,"geteuid") or os.geteuid()==0:
            result=apply(root,vault,baseline,EXPECTED)
            assert result["archived_old_unreviewed_count"]==EXPECTED-2,result
            assert result["still_awaiting_photo_review"]==3,result
            cx=sqlite3.connect(str(live))
            assert cx.execute("SELECT COUNT(*) FROM candidates WHERE status='archived_stale'").fetchone()[0]==EXPECTED-2
            assert cx.execute("SELECT COUNT(*) FROM rg_news2_photo_dispatch").fetchone()[0]==1
            assert cx.execute("SELECT status FROM candidates WHERE id='new'").fetchone()[0]==FROM
            cx.close()
            second=apply(root,vault,baseline,EXPECTED)
            assert second["archived_old_unreviewed_count"]==0,second
    print("RG_NEWS2_OLD_PHOTO_QUEUE_ARCHIVE_SELFTEST_PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=("selftest","apply"))
    args=parser.parse_args()
    try:
        if args.mode=="selftest":
            selftest()
        else:
            print(json.dumps(apply(),sort_keys=True,ensure_ascii=False,indent=2))
    except (RuntimeError,OSError,ValueError,sqlite3.Error) as err:
        print(json.dumps({"status":"SAFE_ABORT",
            "reason_code":str(err) if isinstance(err,RuntimeError) else type(err).__name__,
            "no_telegram_activity":True,
            "no_publications":True,
            "rollback_on_failed_transaction":True},sort_keys=True))
        sys.exit(2)
