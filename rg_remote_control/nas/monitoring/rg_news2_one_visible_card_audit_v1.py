#!/usr/bin/env python3
"""Read-only NEWS RG moderation-card discrepancy audit (Python 3.8+).

Summarizes two unresolved sent-card records (old + newest) without exposing
candidate IDs, Telegram message IDs, chat IDs, media URLs or private text.
Does not query Telegram; can't establish whether a message is visible in app.
"""
import datetime as dt
import json
import pathlib
import sqlite3
import sys
import tempfile
import time

BASE=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
VAULT=pathlib.Path("/volume1/docker/RG_NAS_MONITOR/news2_private_photo_snapshots")
GOOD={"awaiting_photo_review","awaiting_moderation","rejected",
      "accepted","approved","archived_stale","photo_rejected",
      "photo_reviewed","sent","failed"}
EXPECTED_SENT_BASELINE=5

def age(v):
    if v is None:return None
    if isinstance(v,(int,float)):
        n=float(v)
        if n>1e12:n/=1000.0
    elif isinstance(v,str):
        try:
            x=dt.datetime.fromisoformat(v.replace("Z","+00:00"))
            if x.tzinfo is None:x=x.replace(tzinfo=dt.timezone.utc)
            n=x.timestamp()
        except (ValueError,OverflowError):return None
    else:return None
    if n<946684800 or n>4102444800:return None
    return round(max(0,(time.time()-n)/60),1)

def inspect(base=BASE,vault=VAULT):
    db=base/"news.sqlite3"
    if not db.is_file() or db.is_symlink():
        raise RuntimeError("DB_MISSING_OR_SYMLINK")
    conn=sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)
    conn.execute("PRAGMA query_only=ON")
    try:
        names={x[0] for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"rg_news2_photo_dispatch","candidates"}.issubset(names):
            raise RuntimeError("TABLES_MISSING")
        def cols(table):
            return {x[1] for x in conn.execute('PRAGMA table_info("'+table+'")')}
        dcols=cols("rg_news2_photo_dispatch")
        ccols=cols("candidates")
        if not {"candidate_id","telegram_message_id"}.issubset(dcols) or \
           not {"id","photo_reviewed","status"}.issubset(ccols):
            raise RuntimeError("SOURCE_SCHEMA_NOT_PROVEN")
        total,confirmed=conn.execute(
            "SELECT COUNT(*),COUNT(telegram_message_id) FROM rg_news2_photo_dispatch").fetchone()
        query=(
            "SELECT d.rowid,d.telegram_message_id IS NOT NULL,"
            "c.id IS NOT NULL,c.photo_reviewed,c.status" +
            (",d.updated_at" if "updated_at" in dcols else ",NULL")+
            (",c.updated_at" if "updated_at" in ccols else ",NULL")+
            (",c.photo_review_note" if "photo_review_note" in ccols else ",NULL")+
            " FROM rg_news2_photo_dispatch d "
            "LEFT JOIN candidates c ON c.id=d.candidate_id ORDER BY d.rowid")
        rows=conn.execute(query).fetchall()
        entries=[]
        for index,(rowid,has_receipt,linked,reviewed,status,ds,cs,note) in enumerate(rows,1):
            # No raw identifiers or content in the output.
            entries.append({
                "send_order":index,
                "receipt_confirmed":bool(has_receipt),
                "candidate_linked":bool(linked),
                "moderator_decision_recorded":bool(reviewed),
                "candidate_status":status if status in GOOD else "other_redacted",
                "dispatch_updated_age_minutes":age(ds),
                "candidate_updated_age_minutes":age(cs),
                "review_note_present":bool(str(note).strip()) if note is not None else False})
        pending=[e for e in entries if e["receipt_confirmed"] and e["candidate_linked"]
                 and not e["moderator_decision_recorded"]]
        latest=entries[-1] if entries else None
        if total!=confirmed:
            status="UNRECEIPTED_DISPATCH_RECONCILIATION_REQUIRED"
        elif len(pending)==2 and len(entries)==EXPECTED_SENT_BASELINE \
                and {p["send_order"] for p in pending}=={4,5}:
            status="OLDER_FOURTH_AND_NEWEST_FIFTH_BOTH_MARKED_UNREVIEWED"
        elif len(pending)==1 and latest and latest["send_order"]==EXPECTED_SENT_BASELINE:
            status="ONLY_NEWEST_CARD_MARKED_UNREVIEWED"
        elif not pending:
            status="NO_OUTSTANDING_SENT_CARDS"
        else:
            status="CARD_REVIEW_STATE_REQUIRES_MANUAL_CORRELATION"
        uncertain=vault/"rg_news2_private_final_unconfirmed_v1.json"
        if uncertain.is_symlink():raise RuntimeError("UNCERTAINTY_SYMLINK")
        queue=conn.execute("SELECT COUNT(*) FROM candidates WHERE status='awaiting_photo_review'").fetchone()[0]
        out={
            "schema":"NEWS_RG_ONE_VISIBLE_CARD_AUDIT_V1",
            "read_only":True,"telegram_calls":0,"sqlite_writes":0,
            "pollers_started":0,"publications":0,
            "telegram_app_visibility_verified":False,
            "do_not_auto_resolve_invisible_card":True,
            "confirmed_receipts":confirmed,
            "unreceipted_dispatch":total-confirmed,
            "pending_sent_cards":len(pending),
            "pending_sent_card_details":pending,
            "latest_sent_card":latest,
            "queue_waiting_for_photo":queue,
            "new_uncertainty_marker":uncertain.exists(),
            "status":status}
        return out
    finally:
        conn.close()

def selftest():
    with tempfile.TemporaryDirectory() as td:
        p=pathlib.Path(td);v=p/"vault";v.mkdir()
        c=sqlite3.connect(str(p/"news.sqlite3"))
        c.execute("CREATE TABLE candidates(id INTEGER PRIMARY KEY,photo_reviewed INT,status TEXT,"
                  "updated_at TEXT,photo_review_note TEXT)")
        c.execute("CREATE TABLE rg_news2_photo_dispatch("
                  "candidate_id INT,telegram_message_id INT,updated_at TEXT)")
        stamp="2026-10-27T10:00:00+00:00"
        for i in range(1,6):
            reviewed=1 if i<4 else 0
            c.execute("INSERT INTO candidates VALUES (?,?,?,?,?)",
                      (i,reviewed,"awaiting_moderation",stamp,"accepted" if reviewed else None))
            c.execute("INSERT INTO rg_news2_photo_dispatch VALUES(?,?,?)",
                      (i,100+i,stamp))
        c.commit();c.close()
        x=inspect(p,v)
        assert x["status"]=="OLDER_FOURTH_AND_NEWEST_FIFTH_BOTH_MARKED_UNREVIEWED"
        assert [x["send_order"] for x in x["pending_sent_card_details"]]==[4,5]
        assert "101" not in json.dumps(x) and "105" not in json.dumps(x)
        c=sqlite3.connect(str(p/"news.sqlite3"))
        c.execute("UPDATE candidates SET photo_reviewed=1 WHERE id=4")
        c.commit();c.close()
        y=inspect(p,v)
        assert y["status"]=="ONLY_NEWEST_CARD_MARKED_UNREVIEWED"
        c=sqlite3.connect(str(p/"news.sqlite3"))
        c.execute("INSERT INTO rg_news2_photo_dispatch VALUES(?,?,?)",
                  (99,None,stamp))
        c.commit();c.close()
        z=inspect(p,v)
        assert z["status"]=="UNRECEIPTED_DISPATCH_RECONCILIATION_REQUIRED"
    print("NEWS_RG_ONE_VISIBLE_CARD_AUDIT_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["inspect"]:
        print(json.dumps(inspect(),ensure_ascii=False,sort_keys=True,indent=2))
    else:
        raise SystemExit("Only selftest or inspect supported")
