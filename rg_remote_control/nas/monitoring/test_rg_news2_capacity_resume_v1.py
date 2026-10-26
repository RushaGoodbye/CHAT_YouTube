#!/usr/bin/env python3
"""End-to-end isolated capacity-resume regression tests; Python 3.8+.

No real NAS commands, Telegram, polling, publication or production writes.
Tests: stale uncertainty evidence, zero-call normal skip, ambiguous failure,
confirmed one receipt, and bounded outstanding-card capacity.
"""
import ast
import hashlib
import importlib.util
import json
import pathlib
import sqlite3
import tempfile
import time
import types

HERE=pathlib.Path(__file__).parent
PATCHER=HERE/"rg_news2_capacity_resume_v1.py"
ORIGINAL=HERE/"rg_news2_private_final_bundle_v1.py"

def load(path,tag):
    spec=importlib.util.spec_from_file_location(tag,str(path))
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

def fixture(path,open_cards=1):
    root=path/"news";root.mkdir()
    vault=path/"vault";vault.mkdir()
    (root/"operator").mkdir()
    db=root/"news.sqlite3"
    c=sqlite3.connect(str(db))
    c.execute("CREATE TABLE candidates(id INTEGER PRIMARY KEY,status TEXT,photo_reviewed INTEGER,updated_at TEXT)")
    c.execute("CREATE TABLE rg_news2_photo_dispatch(candidate_id INTEGER,state TEXT,telegram_message_id INTEGER,updated_at TEXT)")
    old="2026-10-25T10:00:00+00:00"
    c.executemany("INSERT INTO candidates(status,photo_reviewed,updated_at) VALUES(?,?,?)",
                  [("archived_stale",0,old)]*1353+
                  [("awaiting_photo_review",0,old)]*101)
    for i in range(1,5):
        reviewed=0 if i<=open_cards else 1
        c.execute("INSERT INTO candidates(id,status,photo_reviewed,updated_at) VALUES(?,?,?,?)",
                  (10000+i,"awaiting_moderation",reviewed,old))
        c.execute("INSERT INTO rg_news2_photo_dispatch VALUES(?,?,?,?)",
                  (10000+i,"sent",100+i,old))
    c.commit();c.close()
    marker=vault/"rg_news2_private_final_unconfirmed_v1.json"
    marker.write_text('{"state":"SEND_ATTEMPTED_REQUIRES_RECEIPT"}')
    (root/"rg_news_dsm_tick.sh").write_text("#!/bin/sh\n# RG_NEWS2_PRIVATE_FINAL_V1\n")
    (root/"rg_news2_private_final_guard_v1.py").write_bytes(ORIGINAL.read_bytes())
    return root,vault,db,marker

def test_reconcile():
    with tempfile.TemporaryDirectory() as td:
        mod=load(PATCHER,"capacity_audit_test")
        root,vault,db,marker=fixture(pathlib.Path(td))
        original_source_pins=mod.source_pins
        original_prove=mod.prove_capacity_abort
        try:
            mod.source_pins=lambda root=None: ORIGINAL.read_text()
            mod.prove_capacity_abort=lambda root=None: {"guard_line":326,"deliver_line":343}
            result=mod.reconcile(root,vault)
            assert result["status"]=="CAPACITY_NO_SEND_RECONCILED",result
            assert result["receipt_count"]==4 and result["queue"]==101
            assert marker.is_file()
            # An unreceipted dispatch invalidates automated reconciliation.
            c=sqlite3.connect(str(db))
            c.execute("INSERT INTO rg_news2_photo_dispatch VALUES(?,?,?,?)",
                      (90000,"uncertain",None,"2026-10-25T10:00:00+00:00"))
            c.commit();c.close()
            try:mod.reconcile(root,vault)
            except RuntimeError as e:
                assert str(e)=="PENDING_UNRECEIPTED_DISPATCH_EXISTS"
            else:raise AssertionError("bad receipt ledger must block")
        finally:
            mod.source_pins=original_source_pins
            mod.prove_capacity_abort=original_prove

def test_isolated_ast():
    mod=load(PATCHER,"capacity_ast_test")
    patched=mod.patched_content(ORIGINAL.read_text())
    funcs={n.name:n for n in ast.parse(patched).body if isinstance(n,ast.FunctionDef)}
    assert "private_once" in funcs and "one_canary" in funcs
    assert patched.count("PUBLIC_SEND_FORBIDDEN")==1
    assert patched.count("RSS_DISPATCH_FORBIDDEN")==1
    ns={"ast":ast,"RuntimeError":RuntimeError}
    exec(mod.CAP_HELPER,ns)
    fixture_code=("def run():\n"
       "    if photo_open >= 1: return 'blocked'\n"
       "    return deliver_one()\n")
    tree=ast.parse(fixture_code)
    fn=ns["rg_capacity_relax_exact"](tree.body[0])
    observed=[]
    ctx={"photo_open":1,"deliver_one":lambda:observed.append("sent")}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
                 "ast_fixture","exec"),ctx)
    # Inject observer into AST-transformed private-only function.
    ctx["__rg_observe_private_delivery"]=lambda func,*a,**kw:func(*a,**kw)
    ctx["run"]()
    assert observed==["sent"]
    ctx["photo_open"]=3
    assert ctx["run"]()=="blocked"
    assert observed==["sent"]

def test_no_send_and_fail_closed():
    with tempfile.TemporaryDirectory() as td:
        mod=load(PATCHER,"capacity_tick_test")
        root,vault,db,marker=fixture(pathlib.Path(td))
        original=load(ORIGINAL,"capacity_original_test")
        patched_text=mod.patched_content(ORIGINAL.read_text())
        patched=root/"isolated_guard_test.py";patched.write_text(patched_text)
        guard=load(patched,"capacity_guard_test")
        guard.BASE=root;guard.VAULT=vault;guard.DB=db
        guard.GUARD=patched
        guard.UNCERTAIN=marker
        guard.silence=lambda:False
        # A clean pre-photo early return must not poison future scheduler ticks.
        fake=types.SimpleNamespace(returncode=0,
            stdout=b'{"status":"PRIVATE_BRANCH_EXECUTED","delivery_invocations":0}\n',
            stderr=b"")
        guard.subprocess.run=lambda *a,**k:fake
        marker.unlink()
        result=guard.one_canary()
        assert result["status"]=="NO_PHOTO_ATTEMPTED_NO_MARKER",result
        assert not marker.exists()
        # A failure without receipt is ambiguous and must block all retries.
        guard.subprocess.run=lambda *a,**k:types.SimpleNamespace(
            returncode=2,stdout=b"",stderr=b"")
        result=guard.one_canary()
        assert result["status"]=="CANARY_NOT_CONFIRMED",result
        assert marker.exists()
        result=guard.one_canary()
        assert result["status"]=="UNCONFIRMED_PREVIOUS_SEND_NO_RETRY",result
        marker.unlink()
        # With three outstanding cards, even the initial mark is prohibited.
        c=sqlite3.connect(str(db))
        c.execute("UPDATE candidates SET photo_reviewed=0 WHERE id IN (10001,10002,10003)")
        c.commit();c.close()
        result=guard.one_canary()
        assert result["status"]=="PRIVATE_PHOTO_REVIEW_CAPACITY_3",result
        assert not marker.exists()

if __name__=="__main__":
    test_reconcile()
    test_isolated_ast()
    test_no_send_and_fail_closed()
    print("RG_NEWS2_CAPACITY_RESUME_FULL_OFFLINE_REGRESSION_PASS")
