#!/usr/bin/env python3
"""Realistic offline private photo restore: simulate receipt and rollback."""
import importlib.util
import hashlib
import pathlib
import sqlite3
import tempfile
from types import SimpleNamespace

SRC=pathlib.Path(__file__).with_name("rg_news2_photo_final_batch_v6.py")
spec=importlib.util.spec_from_file_location("rg_news2_v6",str(SRC))
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

def fixture(root,receipt):
    app=root/"RG_TELEGRAM_NEWS_2"
    (app/"operator").mkdir(parents=True)
    vault=root/"vault"
    vault.mkdir(mode=0o700)
    tick=app/"rg_news_dsm_tick.sh"
    tick.write_text("#!/bin/sh\nexit 0\n")
    legacy=app/"rg_v18.py"
    legacy.write_text("def tick():\n    return 0\n")
    worker=app/"telegram_photo_review_flow.py"
    worker.write_text("def claim_one(c):\n    return 1\n"
                      "def deliver_one(c, s, *, chat):\n    return claim_one(c)\n")
    db=app/"news.sqlite3"
    c=sqlite3.connect(db)
    c.execute("CREATE TABLE candidates (status TEXT)")
    c.executemany("INSERT INTO candidates VALUES ('archived_stale')",
                  [() for _ in range(1353)])
    c.execute("INSERT INTO candidates VALUES ('awaiting_photo_review')")
    c.execute("CREATE TABLE rg_news2_photo_dispatch (telegram_message_id INTEGER)")
    c.executemany("INSERT INTO rg_news2_photo_dispatch VALUES (?)",
                  [(1,),(2,),(3,)])
    c.commit()
    c.close()
    out=app/"operator/rg_news2_outbound_queue_v2.py"
    source=("import sqlite3, sys\n"
      "sys.path.insert(0,"+repr(str(app))+")\n"
      "from telegram_photo_review_flow import deliver_one\n"
      "def photo_auto_gate_open(): return True\n"
      "def private_send_only(): return True\n"
      "def run(mode):\n"
      "    if mode=='status': return {'state':'ready'}\n"
      "    if photo_auto_gate_open():\n"
      "        private_send_only()\n"
      "        deliver_one(None,None,chat=1)\n")
    if receipt:
        source+=(
          "        conn=sqlite3.connect("+repr(str(db))+")\n"
          "        conn.execute('INSERT INTO rg_news2_photo_dispatch VALUES (999)')\n"
          "        conn.commit()\n"
          "        conn.close()\n")
    source+=("    return None\n"
             "if __name__=='__main__':\n"
             "    run('photo')\n")
    out.write_text(source)
    M.BASE=app
    M.VAULT=vault
    M.TICK=tick
    M.LEGACY=legacy
    M.OUT=out
    M.PHOTO=worker
    M.DB=db
    M.GUARD=app/"rg_news2_photo_tick_guard_v6.py"
    M.UNCONFIRMED=vault/"rg_news2_photo_unconfirmed_v6.json"
    M.EXPECTED={k:hashlib.sha256(p.read_bytes()).hexdigest()[:12] for k,p in
                (("tick",tick),("legacy",legacy),("out",out),("photo",worker))}
    return app,tick

def exercise(receipt):
    with tempfile.TemporaryDirectory() as td:
        app,tick=fixture(pathlib.Path(td),receipt)
        M.contract()
        M.safe_direct_run_contract()
        original=M.subprocess.run
        requests=[0]
        def intercept(*args,**kwargs):
            command=args[0] if args else []
            if isinstance(command,list) and command[-1:]==["invoke-photo"]:
                requests[0]+=1
                try:
                    M.invoke_pinned_run("photo")
                    return SimpleNamespace(returncode=0,stdout=b"",stderr=b"")
                except Exception:
                    return SimpleNamespace(returncode=2,stdout=b"",stderr=b"")
            return original(*args,**kwargs)
        M.subprocess.run=intercept
        try:
            result=M.install()
            if receipt:
                assert result["result"]=="HOOK_INSTALLED",result
                assert result["canary"]["new_receipts"]==1,result
                assert M.MARK in tick.read_text()
                assert not M.UNCONFIRMED.exists()
            else:
                assert result["result"]=="HOOK_ROLLED_BACK",result
                assert result["canary"]["new_receipts"]==0,result
                assert tick.read_text()=="#!/bin/sh\nexit 0\n"
                assert M.UNCONFIRMED.exists()
                again=M.install()
                assert again["canary"]["status"]=="UNCONFIRMED_PREVIOUS_CANARY_BLOCKS_RETRY"
                assert requests[0]==1,requests
            assert result["new_pollers_started"]==0
            assert result["public_gate_enabled"] is False
        finally:
            M.subprocess.run=original

def test_status_guard_without_return():
    # The actual error in V5: a status check need not contain a Return.
    with tempfile.TemporaryDirectory() as td:
        app,_=fixture(pathlib.Path(td),True)
        text=M.OUT.read_text()
        text=text.replace("if mode=='status': return {'state':'ready'}",
                          "if mode=='status': audit_only='ready'")
        # It may also follow a docstring in run().
        text=text.replace("def run(mode):\n",
                          "def run(mode):\n    '''NEWS2 mode dispatcher.'''\n")
        M.OUT.write_text(text)
        M.EXPECTED["out"]=hashlib.sha256(M.OUT.read_bytes()).hexdigest()[:12]
        assert M.safe_direct_run_contract()["mode_status_guard_checked"] is True

def test_status_guard_must_never_deliver():
    with tempfile.TemporaryDirectory() as td:
        app,_=fixture(pathlib.Path(td),True)
        text=M.OUT.read_text()
        text=text.replace("if mode=='status': return {'state':'ready'}",
                          "if mode=='status': deliver_one(None,None,chat=1)")
        M.OUT.write_text(text)
        M.EXPECTED["out"]=hashlib.sha256(M.OUT.read_bytes()).hexdigest()[:12]
        try:
            M.safe_direct_run_contract()
        except RuntimeError as e:
            assert str(e)=="STATUS_BRANCH_CAN_DELIVER_PHOTO"
        else:
            raise AssertionError("Unsafe status mode permitted")

if __name__=="__main__":
    test_status_guard_without_return()
    test_status_guard_must_never_deliver()
    exercise(True)
    exercise(False)
    print("RG_NEWS2_V6_FULL_CANARY_AND_NO_RETRY_TEST_PASS")
