#!/usr/bin/env python3
"""Read-only static inspection of installed NEWS2 photo review handoffs."""
import ast
import json
import pathlib
import re
import sys

ROOT = pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
FILES = (
    "rg_news_dsm_tick.sh",
    "outbound_tick.sh",
    "moderation_tick.sh",
    "operator/rg_news2_outbound_queue_v2.py",
    "operator/rg_news2_rss_hourly.py",
    "operator/rg_news2_rss_one_shot_safe.py",
    "operator/rg_news2_p31_guarded_callback_once.py",
    "operator/telegram_native_candidate_20261025_v3/activate_native_telegram_on_nas.py",
    "telegram_photo_review_flow.py",
)
API = ("claim_one", "deliver_one", "handle_callback", "validate_photo",
       "init_outbox", "record_sent", "record_uncertain", "send_payload")
STATES = ("awaiting_photo_review", "awaiting_moderation", "photo_reviewed")
TARGETS = ("rg_news2_outbound_queue_v2.py", "rg_news2_rss_hourly.py",
           "rg_news2_rss_one_shot_safe.py", "telegram_photo_review_flow.py")

def inspect(root):
    result=[]
    for rel in FILES:
        path=root/rel
        row={"file":rel,"exists":False}
        if path.is_symlink() or not path.is_file():
            result.append(row);continue
        try:
            if path.stat().st_size>350000:
                row["too_large"]=True;result.append(row);continue
            text=path.read_text(encoding="utf-8",errors="replace")
            row["exists"]=True
            row["worker_reference"]="telegram_photo_review_flow" in text
            row["state_references"]={x:x in text for x in STATES}
            if rel.endswith(".sh"):
                row["script_references"]=[x for x in TARGETS if x in text]
                row["syntax"]="UNTESTED"
            else:
                tree=ast.parse(text)
                row["syntax"]="PASS"
                calls=set()
                for node in ast.walk(tree):
                    if isinstance(node,ast.Call):
                        fn=node.func
                        name=fn.id if isinstance(fn,ast.Name) else (
                            fn.attr if isinstance(fn,ast.Attribute) else "")
                        if name in API:calls.add(name)
                row["photo_api_calls"]=sorted(calls)
                row["functions_defined"]=sorted(
                    node.name for node in tree.body
                    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))
                    and node.name in API)
                row["has_entrypoint"]=any(
                    isinstance(node,ast.If) and "__main__" in ast.dump(node.test)
                    for node in tree.body)
                row["possible_flag_refs"]={
                    "auto_delivery":("auto_delivery" in text.lower()),
                    "gate":("delivery_gate" in text.lower() or "publish_gate" in text.lower()),
                    "photo_review":("photo_review" in text.lower()),
                }
        except (OSError,ValueError,SyntaxError,UnicodeError):
            row["syntax"]="ERROR"
        result.append(row)
    return {"schema":"RG_NEWS2_PHOTO_HANDOFF_V2","read_only":True,
            "network_calls":0,"application_scripts_executed":0,
            "records_modified":0,"files":result}

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        root=pathlib.Path(temp)
        folder=root/"operator";folder.mkdir()
        (folder/"rg_news2_outbound_queue_v2.py").write_text(
            "from telegram_photo_review_flow import claim_one, deliver_one\n"
            "def tick(db):\n  task=claim_one(db)\n  return deliver_one(db,task)\n")
        (root/"rg_news_dsm_tick.sh").write_text("#!/bin/sh\npython3 outbound_tick.sh\n")
        report=inspect(root)
        item=next(x for x in report["files"] if x["file"].endswith("outbound_queue_v2.py"))
        assert item["photo_api_calls"]==["claim_one","deliver_one"]
        assert not any("script" in x for x in report["files"] if not x["exists"])
    print("RG_NEWS2_PHOTO_HANDOFF_V2_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["diagnose"]:
        print(json.dumps(inspect(ROOT),indent=2,sort_keys=True))
    else:raise SystemExit("Usage: selftest or diagnose")
