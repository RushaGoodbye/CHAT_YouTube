#!/usr/bin/env python3
"""NEWS RG read-only readiness for adapting original Telegram NEWS bot.

No bot API calls, poller, network, shell execution, SQL writes, token reads,
source text, URL, secrets or moderator/chat IDs printed.
"""
import ast
import collections
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import time

ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
SHADOW=ROOT/"operator/news_rg_editorial_shadow_v1.sqlite3"
VAULT=pathlib.Path("/volume1/docker/RG_NAS_MONITOR/news2_private_photo_snapshots")
FILES={
 "news2_photo_callback":"telegram_photo_review_flow.py",
 "native_telegram_update_callback":"operator/rg_news2_p31_guarded_callback_once.py",
 "active_sender":"operator/rg_news2_outbound_queue_v2.py",
 "active_dsm_guard":"rg_news2_private_final_guard_v1.py",
 "active_tick":"rg_news_dsm_tick.sh",
 "editorial_writer":"operator/news_rg_editorial_rewrite_shadow_v1.py",
 "approved_source_collector":"operator/news_rg_source_shadow_ingest_v1.py",
 "manual_link_adapter":"operator/news_rg_manual_link_v1.py",
}
REPORT_ONLY={"id","candidate_id","photo_url","caption","body","text",
             "source","status","created_at","updated_at"}
def table(cx,name):
    if name not in {x[0] for x in cx.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}:
        return False,set()
    return True,{x[1] for x in cx.execute(
        'PRAGMA table_info("'+name+'")')}

def shape(root=ROOT):
    items={}
    for name,relative in FILES.items():
        path=root/relative
        present=path.is_file() and not path.is_symlink()
        result={"present":present}
        if present and relative.endswith(".py"):
            try:
                doc=ast.parse(path.read_text(encoding="utf-8"))
                fun={x.name for x in doc.body
                      if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef))}
                result["syntax_valid"]=True
                result["handler_shape"]={
                    "callback_handler": "handle_callback" in fun,
                    "message_handler": "handle_message" in fun,
                    "update_handler": "handle_update" in fun,
                    "run": "run" in fun,
                    "main": "main" in fun,
                    "deliver_one": "deliver_one" in fun,
                    "send_payload": "send_payload" in fun,
                    "source_import": "import_manual" in fun}
            except (SyntaxError,UnicodeError,OSError):
                result["syntax_valid"]=False
        items[name]=result
    return items

def inspect(root=ROOT,vault=VAULT,environ=None):
    environ=os.environ if environ is None else environ
    report={"schema":"NEWS_RG_EDITORIAL_INTEGRATION_PREFLIGHT_V1",
            "read_only":True,"no_getupdates":True,"telegram_calls":0,
            "publications":0,"pollers_started":0,"db_writes":0,
            "existing_bot_modules":shape(root),
            "unconfirmed_send_marker":False,
            "shadow_database_present":False,
            "shadow_stories":0,"shadow_pending_editorial":0,
            "shadow_editorial_ready":0,"shadow_manual_link_stories":0,
            "latest_shadow_stage_age_minutes":None,
            "moderation_schema":{},
            "editorial_auth":{"gemini_key_in_command_environment":bool(
                environ.get("GEMINI_API_KEY")),
                "news_rg_ai_explicitly_enabled":environ.get(
                    "NEWS_RG_AI_ALLOWED")=="1",
                "configured_secrets_file_not_opened":True},
            "auth_note":"sudo shell env is not sufficient to prove provider availability "
                        "in Docker or other secured runtimes"}
    marker=vault/"rg_news2_private_final_unconfirmed_v1.json"
    if marker.is_symlink():raise RuntimeError("UNCONFIRMED_MARKER_SYMLINK")
    report["unconfirmed_send_marker"]=marker.is_file()
    db=root/"news.sqlite3"
    if db.is_file() and not db.is_symlink():
        cx=sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)
        cx.execute("PRAGMA query_only=ON")
        try:
            present,ccols=table(cx,"candidates")
            m={"table_exists":present,
               "has_status":"status" in ccols,
               "has_photo_reviewed":"photo_reviewed" in ccols,
               "has_full_news_body":bool({"body","text"}&ccols),
               "has_caption":"caption" in ccols}
            _,dcols=table(cx,"rg_news2_photo_dispatch")
            m.update({"dispatch_has_candidate_id":"candidate_id" in dcols,
                "dispatch_has_confirmed_receipt":"telegram_message_id" in dcols})
            if {"status","photo_reviewed"}.issubset(ccols):
                m["rejected_but_unreviewed"]=cx.execute(
                    "SELECT COUNT(*) FROM candidates WHERE status='rejected' "
                    "AND COALESCE(photo_reviewed,0)=0").fetchone()[0]
            report["moderation_schema"]=m
        finally:cx.close()
    shadow=root/"operator/news_rg_editorial_shadow_v1.sqlite3"
    if shadow.is_file() and not shadow.is_symlink():
        cx=sqlite3.connect(shadow.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)
        cx.execute("PRAGMA query_only=ON")
        try:
            shadow_table,_=table(cx,"story_shadow")
            draft_table,_=table(cx,"editorial_draft")
            if shadow_table:
                statuses=dict(cx.execute("SELECT status,COUNT(*) FROM story_shadow "
                                        "GROUP BY status"))
                report["shadow_database_present"]=True
                report["shadow_stories"]=sum(statuses.values())
                report["shadow_pending_editorial"]=statuses.get(
                    "needs_editorial_rewrite",0)
                report["shadow_editorial_ready"]=statuses.get(
                    "editorial_ready",0)
                report["shadow_manual_link_stories"]=cx.execute(
                    "SELECT COUNT(*) FROM story_shadow WHERE origin='manual_link' "
                    ).fetchone()[0]
                stamp=cx.execute("SELECT MAX(queued_at) FROM story_shadow").fetchone()[0]
                if stamp and isinstance(stamp,int):
                    report["latest_shadow_stage_age_minutes"]=round(
                        max(0,time.time()-stamp)/60,1)
            report["shadow_draft_table_present"]=draft_table
        finally:cx.close()
    report["safe_to_send_editorial_preview"]=bool(
        report["shadow_editorial_ready"]>0 and not report["unconfirmed_send_marker"]
        and report["existing_bot_modules"]["active_sender"]["present"])
    # This is only a prerequisite: no adapter is enabled.
    report["new_editorial_preview_transport_enabled"]=False
    report["manual_link_receiving_in_existing_owner_enabled"]=False
    report["source_ingest_on_dsm_scheduler_enabled"]=False
    return report

def selftest():
    with tempfile.TemporaryDirectory() as td:
        root=pathlib.Path(td);(root/"operator").mkdir()
        vault=root/"vault";vault.mkdir()
        d=sqlite3.connect(str(root/"news.sqlite3"))
        d.execute("CREATE TABLE candidates(status TEXT,photo_reviewed INT,caption TEXT)")
        d.execute("INSERT INTO candidates VALUES('rejected',0,'Private text')")
        d.execute("CREATE TABLE rg_news2_photo_dispatch("
                  "candidate_id INTEGER,telegram_message_id INTEGER)")
        d.commit();d.close()
        s=sqlite3.connect(str(root/"operator/news_rg_editorial_shadow_v1.sqlite3"))
        s.execute("CREATE TABLE story_shadow(status TEXT,origin TEXT,queued_at INT)")
        s.execute("CREATE TABLE editorial_draft(key TEXT)")
        s.execute("INSERT INTO story_shadow VALUES('needs_editorial_rewrite',"
                  "'approved_source',100)")
        s.commit();s.close()
        r=inspect(root,vault,environ={"GEMINI_API_KEY":"SECRET_NOT_FOR_OUTPUT"})
        assert r["shadow_pending_editorial"]==1
        assert r["moderation_schema"]["rejected_but_unreviewed"]==1
        assert r["editorial_auth"]["gemini_key_in_command_environment"]
        assert "SECRET_NOT_FOR_OUTPUT" not in json.dumps(r)
        assert r["telegram_calls"]==0 and not r["new_editorial_preview_transport_enabled"]
    print("NEWS_RG_EDITORIAL_INTEGRATION_PREFLIGHT_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["inspect"]:
        print(json.dumps(inspect(),sort_keys=True,ensure_ascii=False,indent=2))
    else:
        raise SystemExit("Only selftest and inspect supported")
