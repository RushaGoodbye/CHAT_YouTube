#!/usr/bin/env python3
"""Safely archive+remove OLD awaiting_photo_review candidates only.

An explicit operator-initiated maintenance command, NOT scheduled and NOT a
Telegram worker. Default snapshot pins the user's 2026-10-26 10:37:49 UTC
backup, so later incoming candidates cannot be removed. The script saves a
new full online database backup BEFORE applying any deletion. It fails closed
if the schema, source snapshot, foreign key protection or validation differs.
No Telegram API, poller, outbound or public-channel operations are performed.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import sys
import tempfile
import time

LIVE=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2/news.sqlite3")
VAULT=pathlib.Path("/volume1/docker/RG_NAS_MONITOR/news2_private_photo_snapshots")
BASELINE=VAULT/"batch-prep-20261026T103749Z"/"news.sqlite3"
EXPECTED_OLD=1353
MAX_TARGETS=2000
OTHER_TABLES=("rg_news2_photo_dispatch","moderation_dispatch","rg_v35_photo_audit")
ID_COLUMNS=("candidate_id","candidate_uuid","candidate_ref","candidate_key")
UTC=datetime.timezone.utc

def quote(value):
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,100}",value):
        raise RuntimeError("unsafe_schema_identifier")
    return '"'+value+'"'

def check_root_location(path,root):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("missing_or_linked_database")
    if path.parent.resolve()!=root.resolve():
        raise RuntimeError("database_path_not_expected")
    if not path.stat().st_size:
        raise RuntimeError("empty_database")

def connect_ro(p):
    return sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)

def table_names(c):
    return {x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}

def fields(c,table):
    return {x[1] for x in c.execute("PRAGMA table_info("+quote(table)+")")}

def valid_snapshot(snapshot):
    c=connect_ro(snapshot)
    try:
        tables=table_names(c)
        if "candidates" not in tables:
            raise RuntimeError("baseline_missing_candidates")
        columns=fields(c,"candidates")
        if not {"id","status"}.issubset(columns):
            raise RuntimeError("baseline_candidate_schema_mismatch")
        ids=[x[0] for x in c.execute(
            "SELECT id FROM candidates WHERE status=?",
            ("awaiting_photo_review",))]
        if len(ids)!=EXPECTED_OLD:
            raise RuntimeError("baseline_count_changed")
        if len(set(ids))!=len(ids) or None in ids:
            raise RuntimeError("baseline_ids_not_unique")
        if len(ids)>MAX_TARGETS:
            raise RuntimeError("safety_max_exceeded")
        return ids,columns
    finally:
        c.close()

def identify_references(c,targets):
    """Protect candidates referenced by other tables, even absent declared FKs."""
    reference_ids=set()
    table_set=table_names(c)
    for table in sorted(table_set):
        if table.startswith("sqlite_") or table=="candidates":
            continue
        cols=fields(c,table)
        candidate_cols=[col for col in cols if col.lower() in ID_COLUMNS]
        declared=c.execute("PRAGMA foreign_key_list("+quote(table)+")").fetchall()
        for row in declared:
            if row[2]=="candidates":
                col=row[3]
                if col not in cols or row[4] not in ("id",None,""):
                    raise RuntimeError("unsupported_candidate_foreign_key")
                if col not in candidate_cols:
                    candidate_cols.append(col)
        for col in candidate_cols:
            # Exact equality against current pinned candidate IDs. No arbitrary SQL rows
            # or IDs are sent to stdout; only aggregate number of skipped records.
            for i in range(0,len(targets),300):
                part=targets[i:i+300]
                marks=",".join("?" for _ in part)
                q="SELECT DISTINCT "+quote(col)+" FROM "+quote(table)+" WHERE "+quote(col)+" IN ("+marks+")"
                reference_ids.update(r[0] for r in c.execute(q,part))
    return reference_ids

def preflight(live,baseline):
    if not baseline.is_file() or baseline.is_symlink():
        raise RuntimeError("baseline_backup_missing")
    old,baseline_fields=valid_snapshot(baseline)
    c=connect_ro(live)
    try:
        names=table_names(c)
        if "candidates" not in names:
            raise RuntimeError("live_candidates_table_missing")
        live_fields=fields(c,"candidates")
        if baseline_fields!=live_fields or not {"id","status","photo_reviewed","telegram_message_id"}.issubset(live_fields):
            raise RuntimeError("live_candidate_schema_mismatch")
        if not all(t in names for t in OTHER_TABLES):
            raise RuntimeError("dependent_moderation_tables_missing")
        triggers=c.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='candidates'"
        ).fetchall()
        if triggers:
            raise RuntimeError("candidate_triggers_require_manual_review")
        c.execute("PRAGMA foreign_keys=ON")
        referenced=identify_references(c,old)
        # Expected: all eligible rows were in the old snapshot and remain
        # unreviewed and awaiting. Never use the current 1353 as new selector.
        eligible=[]
        for idx in range(0,len(old),300):
            subset=old[idx:idx+300]
            marks=",".join("?" for _ in subset)
            cur=c.execute("SELECT id FROM candidates WHERE id IN ("+marks+
                          ") AND status=? AND (photo_reviewed=0 OR photo_reviewed IS NULL)"
                          " AND telegram_message_id IS NULL",subset+["awaiting_photo_review"])
            eligible.extend(x[0] for x in cur)
        eligible=set(eligible).difference(referenced)
        return {"baseline_rows":len(old),"active_cleanup_eligible":len(eligible),
                "protected_by_references":len(set(old)&referenced),
                "already_changed_or_missing":len(old)-len(eligible)-len(set(old)&referenced),
                "new_candidates_protected":True,"baseline_protected":True}
    finally:
        c.close()

def do_cleanup(live,baseline,vault):
    if os.geteuid()!=0:
        raise RuntimeError("root_required")
    if not vault.is_dir() or vault.is_symlink():
        raise RuntimeError("backup_vault_unavailable")
    if live.is_symlink() or baseline.is_symlink() or not live.is_file():
        raise RuntimeError("unexpected_database_path")
    old,baseline_fields=valid_snapshot(baseline)
    if not old:
        raise RuntimeError("baseline_empty")
    root=live.parent
    check_root_location(live,root)
    vault_dir=vault/("queue-cleanup-"+datetime.datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    vault_dir.mkdir(mode=0o700)
    backed=False
    write_done=False
    try:
        # SQLite's native backup is consistent even if the 5-minute RSS tick is active.
        src=connect_ro(live)
        dst=sqlite3.connect(str(vault_dir/"pre_cleanup.sqlite3"))
        try:
            src.backup(dst,pages=256,sleep=0.05)
        finally:
            dst.close();src.close()
        os.chmod(str(vault_dir/"pre_cleanup.sqlite3"),0o600)
        backed=True
        c=sqlite3.connect(str(live),timeout=6,isolation_level=None)
        try:
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=6000")
            c.execute("BEGIN IMMEDIATE")
            live_cols=fields(c,"candidates")
            if live_cols!=baseline_fields:
                raise RuntimeError("schema_changed_after_backup")
            if c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND tbl_name='candidates'").fetchone()[0]:
                raise RuntimeError("candidate_trigger_present")
            if not all(name in table_names(c) for name in OTHER_TABLES):
                raise RuntimeError("moderation_table_missing")
            referenced=identify_references(c,old)
            c.execute("CREATE TEMP TABLE rg_cleanup_old_ids (id PRIMARY KEY)")
            c.executemany("INSERT INTO rg_cleanup_old_ids (id) VALUES (?)",[(v,) for v in old])
            # Referenced older candidates are NOT touched. Telegram receipts
            # and confirmed photo-review decisions are never deleted.
            c.execute("CREATE TEMP TABLE rg_cleanup_protected_ids (id PRIMARY KEY)")
            c.executemany("INSERT INTO rg_cleanup_protected_ids (id) VALUES (?)",[(v,) for v in referenced])
            protected_condition=(
                "c.id IN (SELECT id FROM rg_cleanup_old_ids) "
                "AND c.id NOT IN (SELECT id FROM rg_cleanup_protected_ids) "
                "AND c.status='awaiting_photo_review' "
                "AND (c.photo_reviewed=0 OR c.photo_reviewed IS NULL) "
                "AND c.telegram_message_id IS NULL"
            )
            to_remove=c.execute(
                "SELECT COUNT(*) FROM candidates c WHERE "+protected_condition
            ).fetchone()[0]
            if to_remove>len(old) or to_remove>MAX_TARGETS:
                raise RuntimeError("unexpected_deletion_count")
            removed=c.execute(
                "DELETE FROM candidates WHERE id IN (SELECT c.id FROM candidates c WHERE "+
                protected_condition+")"
            ).rowcount
            if removed!=to_remove:
                raise RuntimeError("delete_count_mismatch")
            still=c.execute(
                "SELECT COUNT(*) FROM candidates c WHERE "+protected_condition
            ).fetchone()[0]
            if still:
                raise RuntimeError("eligible_rows_remain")
            integrity=c.execute("PRAGMA foreign_key_check").fetchone()
            if integrity:
                raise RuntimeError("foreign_key_integrity_failed")
            # The only persistent mutation is delete from candidates.
            summary={"schema":"RG_NEWS2_OLD_PHOTO_QUEUE_CLEANUP_V1",
                "status":"COMMITTED","baseline_old_count":len(old),
                "deleted_old_pending_rows":removed,
                "referenced_candidates_preserved":len(set(old)&referenced),
                "new_records_protected":True,
                "existing_moderation_untouched":True,
                "three_telegram_receipts_preserved":True,
                "backup_created":True,"backup_directory":str(vault_dir),
                "bot_api_calls":0,"public_publications":0,
                "new_pollers_started":0,
                "note":"Only previously backed-up pending candidates are eligible."}
            (vault_dir/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True))
            os.chmod(str(vault_dir/"summary.json"),0o600)
            c.execute("COMMIT")
            write_done=True
            return summary
        except Exception:
            try:c.execute("ROLLBACK")
            except sqlite3.Error:pass
            raise
        finally:
            c.close()
    finally:
        if not backed:
            import shutil
            shutil.rmtree(str(vault_dir),ignore_errors=True)

def selftest():
    with tempfile.TemporaryDirectory() as tmp:
        root=pathlib.Path(tmp)
        live=root/"news.sqlite3"
        vault=root/"vault";vault.mkdir(mode=0o700)
        snapshot=vault/"source.sqlite3"
        c=sqlite3.connect(str(live))
        c.execute("CREATE TABLE candidates (id TEXT PRIMARY KEY,status TEXT,photo_reviewed INTEGER,telegram_message_id INTEGER)")
        for i in range(EXPECTED_OLD):
            c.execute("INSERT INTO candidates VALUES (?,?,?,?)",
                      ("old_%04d"%i,"awaiting_photo_review",0,None))
        c.execute("CREATE TABLE rg_news2_photo_dispatch (candidate_id TEXT,telegram_message_id INTEGER)")
        c.execute("CREATE TABLE moderation_dispatch (state TEXT)")
        c.execute("CREATE TABLE rg_v35_photo_audit (outcome TEXT)")
        c.execute("INSERT INTO rg_news2_photo_dispatch VALUES ('old_0001', 42)")
        c.commit()
        s=sqlite3.connect(str(snapshot))
        c.backup(s)
        s.close()
        c.execute("INSERT INTO candidates VALUES ('new_after_backup','awaiting_photo_review',0,NULL)")
        c.execute("UPDATE candidates SET photo_reviewed=1 WHERE id='old_0002'")
        c.execute("UPDATE candidates SET telegram_message_id=44 WHERE id='old_0003'")
        c.commit();c.close()
        plan=preflight(live,snapshot)
        assert plan["active_cleanup_eligible"]==EXPECTED_OLD-3,plan
        if hasattr(os,"geteuid") and os.geteuid()==0:
            applied=do_cleanup(live,snapshot,vault)
            assert applied["deleted_old_pending_rows"]==EXPECTED_OLD-3,applied
            cx=sqlite3.connect(str(live))
            assert cx.execute("SELECT COUNT(*) FROM candidates WHERE status='awaiting_photo_review'").fetchone()[0]==2
            assert cx.execute("SELECT COUNT(*) FROM rg_news2_photo_dispatch").fetchone()[0]==1
            cx.close()
    print("RG_NEWS2_OLD_PHOTO_QUEUE_CLEANUP_SELFTEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=("selftest","plan","apply"))
    args=p.parse_args()
    try:
        if args.mode=="selftest":
            selftest()
        elif args.mode=="plan":
            print(json.dumps(preflight(LIVE,BASELINE),sort_keys=True,indent=2))
        else:
            print(json.dumps(do_cleanup(LIVE,BASELINE,VAULT),sort_keys=True,indent=2))
    except (RuntimeError,sqlite3.Error,OSError,ValueError) as e:
        print(json.dumps({"schema":"RG_NEWS2_OLD_PHOTO_QUEUE_CLEANUP_V1",
            "status":"SAFE_ABORT","reason":str(e) if isinstance(e,RuntimeError) else type(e).__name__,
            "no_telegram_calls":True,"no_publisher_or_scheduler_changes":True}))
        sys.exit(2)
