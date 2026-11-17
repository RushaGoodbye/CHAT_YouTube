#!/usr/bin/env python3
"""Offline integration tests: no Telegram network, no production NAS paths."""
import importlib.util
import json
import pathlib
import sqlite3
import tempfile

MODULE_FILE=pathlib.Path(__file__).with_name("rg_news2_photo_tick_integrator_v2.py")
spec=importlib.util.spec_from_file_location("news2_photo_tick",str(MODULE_FILE))
M=importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

def scenario(where,send_receipt,drop_private_gate=False,flag_cli=False):
    root=where/"RG_TELEGRAM_NEWS_2";root.mkdir()
    (root/"operator").mkdir()
    vault=where/"vault";vault.mkdir(mode=0o700)
    tick=root/"rg_news_dsm_tick.sh"
    tick.write_text("#!/bin/sh\nexit 0\n")
    legacy=root/"rg_v18.py";legacy.write_text("def tick():\n  pass\n")
    photo=root/"telegram_photo_review_flow.py"
    photo.write_text("def claim_one(c):\n  return 1\n"
                     "def deliver_one(c,send_photo,*,chat):\n  return claim_one(c)\n")
    database=root/"news.sqlite3"
    conn=sqlite3.connect(str(database))
    conn.execute("CREATE TABLE candidates(status TEXT)")
    conn.executemany("INSERT INTO candidates VALUES('archived_stale')",[() for _ in range(1353)])
    conn.execute("INSERT INTO candidates VALUES('awaiting_photo_review')")
    conn.execute("CREATE TABLE rg_news2_photo_dispatch(telegram_message_id INTEGER)")
    conn.executemany("INSERT INTO rg_news2_photo_dispatch VALUES(?)",[(1,),(2,),(3,)])
    conn.commit();conn.close()
    outbound=root/"operator/rg_news2_outbound_queue_v2.py"
    code=(
      "import sqlite3,sys,argparse\n"
      "sys.path.insert(0, "+repr(str(root))+")\n"
      "from telegram_photo_review_flow import deliver_one\n"
      "def photo_auto_gate_open(): return True\n"
      "def private_send_only(): return True\n"
      "def run(mode):\n"
      "  if mode=='photo':\n"
      "    if photo_auto_gate_open():\n"
      + ("" if drop_private_gate else "      private_send_only()\n")
      + "      deliver_one(None,None,chat=1)\n"
      "  return None\n"
      "if __name__=='__main__':\n"
      + (("  parser=argparse.ArgumentParser()\n"
          "  parser.add_argument('--mode',choices=['status','photo'],required=True)\n"
          "  parsed=parser.parse_args()\n"
          "  run(parsed.mode)\n") if flag_cli else "  run(sys.argv[1])\n"))
    if send_receipt:
        code+=(
          "  c=sqlite3.connect("+repr(str(database))+")\n"
          "  c.execute('INSERT INTO rg_news2_photo_dispatch VALUES(999)')\n"
          "  c.commit()\n"
          "  c.close()\n")
    outbound.write_text(code)
    M.BASE=root;M.VAULT=vault;M.TICK=tick;M.LEGACY=legacy
    M.OUT=outbound;M.PHOTO=photo;M.DB=database
    M.GUARD=root/"rg_news2_photo_tick_guard_v1.py"
    M.EXPECTED={key:M.digest(p) for key,p in
                (("tick",tick),("legacy",legacy),("out",outbound),("photo",photo))}
    M.contract()
    got=M.install()
    return got,tick.read_text(),M.MARK

def test_success():
    with tempfile.TemporaryDirectory() as temp:
        result,tick,mark=scenario(pathlib.Path(temp),True)
        assert result["result"]=="HOOK_INSTALLED",result
        assert result["canary"]["new_receipts"]==1,result
        assert result["canary"]["new_photo_rows"]==1,result
        assert mark in tick
        assert result["new_pollers_started"]==0

def test_rollback():
    with tempfile.TemporaryDirectory() as temp:
        result,tick,mark=scenario(pathlib.Path(temp),False)
        assert result["result"]=="HOOK_ROLLED_BACK",result
        assert result["canary"]["new_receipts"]==0,result
        assert tick=="#!/bin/sh\nexit 0\n"
        assert mark not in tick

def test_required_mode_flag():
    with tempfile.TemporaryDirectory() as temp:
        result,tick,mark=scenario(pathlib.Path(temp),True,flag_cli=True)
        assert result["result"]=="HOOK_INSTALLED",result
        assert result["canary"]["new_receipts"]==1,result
        assert result["canary"]["photo_cli_style"]=="flag",result
        assert mark in tick

def test_missing_private_safety_call_fails_closed():
    with tempfile.TemporaryDirectory() as temp:
        try:
            scenario(pathlib.Path(temp),False,drop_private_gate=True)
        except RuntimeError as exc:
            assert "PRIVATE_PHOTO_SAFETY_CALLS_MISSING:private_send_only" in str(exc)
        else:
            raise AssertionError("Missing private-send guard must fail closed")

if __name__=="__main__":
    test_success()
    test_rollback()
    test_required_mode_flag()
    test_missing_private_safety_call_fails_closed()
    print("RG_NEWS2_PRIVATE_PHOTO_V2_CLI_AND_ROLLBACK_TEST_PASS")
