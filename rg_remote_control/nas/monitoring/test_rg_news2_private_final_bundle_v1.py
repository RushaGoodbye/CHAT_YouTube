#!/usr/bin/env python3
"""Isolated fake-NAS end-to-end tests: exact one card vs failed guard."""
import hashlib
import importlib.util
import json
import pathlib
import sqlite3
import tempfile
from types import SimpleNamespace

SRC=pathlib.Path(__file__).with_name("rg_news2_private_final_bundle_v1.py")
spec=importlib.util.spec_from_file_location("news2private",str(SRC))
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

def fixture(root,break_gates=False):
    app=root/"rg"
    (app/"operator").mkdir(parents=True)
    vault=root/"vault"
    vault.mkdir(mode=0o700)
    tick=app/"rg_news_dsm_tick.sh"
    tick.write_text("#!/bin/sh\nexit 0\n")
    legacy=app/"rg_v18.py"
    legacy.write_text("def tick():return 0\n")
    db=app/"news.sqlite3"
    c=sqlite3.connect(db)
    c.execute("CREATE TABLE candidates(status TEXT)")
    c.executemany("INSERT INTO candidates VALUES (?)",
       [("archived_stale",)]*1353+[("awaiting_photo_review",)]*79)
    c.execute("CREATE TABLE rg_news2_photo_dispatch (telegram_message_id INTEGER)")
    c.executemany("INSERT INTO rg_news2_photo_dispatch VALUES (?)",[(1,),(2,),(3,)])
    c.commit();c.close()
    worker=app/"telegram_photo_review_flow.py"
    worker.write_text(
        "def claim_one(conn):\n"
        "    conn.execute('UPDATE candidates SET status=? WHERE rowid=(SELECT rowid FROM candidates WHERE status=? LIMIT 1)',('photo_sent','awaiting_photo_review'))\n"
        "def record_uncertain(conn):\n"
        "    return False\n"
        "def record_sent(conn):\n"
        "    conn.execute('INSERT INTO rg_news2_photo_dispatch VALUES (999)')\n"
        "def deliver_one(conn,chat_id,send_photo):\n"
        "    if False:record_uncertain(conn)\n"
        "    claim_one(conn)\n"
        "    record_sent(conn)\n"
        "    conn.commit()\n")
    out=app/"operator/rg_news2_outbound_queue_v2.py"
    out.write_text(
        "import sqlite3\n"
        "def gates():\n"
        +("    raise RuntimeError('EXPECTED_SAFE_STOP')\n" if break_gates else "    return None\n")+
        "def photo_auto_gate_open():return True\n"
        "def private_send_only(module,chat_id):return True\n"
        "def maybe_rss_hourly():raise RuntimeError('RSS_CALLED')\n"
        "def send_one():raise RuntimeError('PUBLIC_CALLED')\n"
        "def standard_dispatch_source_safe(module):raise RuntimeError('PUBLIC_CALLED')\n"
        "def db_connect():return sqlite3.connect("+repr(str(db))+")\n"
        "def run(mode):\n"
        "    if mode not in ('status','tick'):raise RuntimeError('bad mode')\n"
        "    gates()\n"
        "    enabled=photo_auto_gate_open()\n"
        "    if mode=='tick' and not enabled:return\n"
        "    if mode=='tick': maybe_rss_hourly()\n"
        "    conn=db_connect()\n"
        "    ordinary_open=1\n"
        "    photo_open=1\n"
        "    accepted_waiting=True\n"
        "    try:\n"
        "        if accepted_waiting:\n"
        "            if not standard_dispatch_source_safe(None): raise RuntimeError('ordinary')\n"
        "            if ordinary_open>=1:pass\n"
        "        if ordinary_open>=1:send_one()\n"
        "        if photo_open>=1:\n"
        "            private_send_only(None,42)\n"
        "            import telegram_photo_review_flow as p\n"
        "            p.deliver_one(conn,42,lambda payload:None)\n"
        "    finally:conn.close()\n"
        "if __name__=='__main__':run('tick')\n")
    # Make imports work in test-generated private child without full NAS.
    import sys
    sys.path.insert(0,str(app))
    M.BASE=app;M.VAULT=vault;M.TICK=tick;M.LEGACY=legacy
    M.OUT=out;M.PHOTO=worker;M.DB=db
    M.GUARD=app/"rg_news2_private_final_guard_v1.py"
    M.OLD_UNCERTAIN=vault/"rg_news2_photo_unconfirmed_v6.json"
    M.UNCERTAIN=vault/"rg_news2_private_final_unconfirmed_v1.json"
    M.OLD_UNCERTAIN.write_text(json.dumps({"state":"SEND_ATTEMPTED_REQUIRES_RECEIPT"}))
    M.EXPECTED={k:hashlib.sha256(f.read_bytes()).hexdigest()[:12]
        for k,f in (("tick",tick),("legacy",legacy),("out",out),("photo",worker))}
    return tick,db

def scenario(break_gates):
    with tempfile.TemporaryDirectory() as tmp:
        tick,db=fixture(pathlib.Path(tmp),break_gates)
        # Test synthetic source has the same dispatch points as pinned NAS:
        # normal send and RSS must be absent from the executed AST.
        original=M.subprocess.run
        calls=[0]
        def child(*args,**kwargs):
            cmd=args[0] if args else ()
            if isinstance(cmd,list) and cmd[-1:]==["child"]:
                calls[0]+=1
                try:
                    M.private_once()
                    return SimpleNamespace(returncode=0,stdout=b"",stderr=b"")
                except Exception:
                    return SimpleNamespace(returncode=2,stdout=b"",stderr=b"")
            return original(*args,**kwargs)
        M.subprocess.run=child
        original_uid=M.os.geteuid
        M.os.geteuid=lambda:0
        try:
            result=M.install()
            c=sqlite3.connect(db)
            receipts=c.execute("SELECT COUNT(*) FROM rg_news2_photo_dispatch WHERE telegram_message_id IS NOT NULL").fetchone()[0]
            pending=c.execute("SELECT COUNT(*) FROM candidates WHERE status='awaiting_photo_review'").fetchone()[0]
            c.close()
            if break_gates:
                assert result["result"]=="NOT_INSTALLED_PRIVATE_CANARY_UNCONFIRMED",result
                assert receipts==3 and pending==79
                assert M.UNCERTAIN.exists()
                assert M.MARK not in tick.read_text()
                again=M.install()
                assert again["result"]=="SAFE_BLOCKED_UNCERTAIN_SEND",again
                assert calls[0]==1,calls
            else:
                assert result["result"]=="HOOK_INSTALLED",result
                assert receipts==4 and pending==78,(receipts,pending)
                assert not M.UNCERTAIN.exists()
                assert M.MARK in tick.read_text()
                assert M.OLD_UNCERTAIN.exists()
                assert M.source_contract()[0]["private_branch_kept"]
                assert calls[0]==1,calls
        finally:
            M.subprocess.run=original
            M.os.geteuid=original_uid

if __name__=="__main__":
    scenario(False)
    scenario(True)
    print("RG_NEWS2_FINAL_FAKE_NAS_ONE_RECEIPT_NO_PUBLIC_ROLLBACK_PASS")
