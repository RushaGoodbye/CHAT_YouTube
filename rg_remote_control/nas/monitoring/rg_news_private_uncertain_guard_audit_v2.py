#!/usr/bin/env python3
"""Read-only receipt counts and static no-retry sender guard verification."""
import argparse,ast,hashlib,json
from collections import Counter
from pathlib import Path

ROOT=Path("/volume1/docker/RG_TELEGRAM_NEWS_2/operator")
RECEIPT="news_rg_private_multipart_receipts_v1"
SENDER="news_rg_durable_private_sender_v1.py"

class Stop(ValueError): pass

def static_guard(source):
    tree=ast.parse(source)
    guards=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.If):
            test=" ".join(n.value for n in ast.walk(node.test) if isinstance(n,ast.Constant) and isinstance(n.value,str))+" "+ " ".join(n.id for n in ast.walk(node.test) if isinstance(n,ast.Name))
            body=" ".join(n.value for sub in node.body for n in ast.walk(sub) if isinstance(n,ast.Constant) and isinstance(n.value,str))
            body+=" "+ " ".join(n.id for sub in node.body for n in ast.walk(sub) if isinstance(n,ast.Name))
            if "status" in test and "SENDING_UNCERTAIN" in test and "PAUSED_UNCERTAIN_DELIVERY_REQUIRES_REVIEW" in body:
                guards.add("sending_uncertain")
            if "status" in test and "UNCERTAIN_NO_RETRY" in test and "HTTP_REJECTED_NO_RETRY" in test and ("die(" in body or "raise " in body):
                guards.add("no_retry_receipts")
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=="open":
            if isinstance(node.func.value,ast.Name) and node.func.value.id=="os":
                args=" ".join(n.attr for x in node.args for n in ast.walk(x) if isinstance(n,ast.Attribute))
                if "O_CREAT" in args and "O_EXCL" in args:
                    guards.add("exclusive_receipt")
    return guards

def report(root=ROOT):
    p=root/RECEIPT
    if not p.is_dir() or p.is_symlink():raise Stop("RECEIPTS_UNAVAILABLE")
    counts=Counter();examples=[]
    for file in p.glob("*.json"):
        if not file.is_file() or file.is_symlink() or file.stat().st_size>20000:
            raise Stop("RECEIPT_FILE_UNSAFE")
        item=json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(item,dict):raise Stop("RECEIPT_NOT_OBJECT")
        status=item.get("status")
        if not isinstance(status,str) or len(status)>60:raise Stop("STATUS_INVALID")
        counts[status]+=1
        if status in ("SENDING_UNCERTAIN","UNCERTAIN_NO_RETRY","HTTP_REJECTED_NO_RETRY"):
            examples.append({"receipt_ref":hashlib.sha256(file.name.encode()).hexdigest()[:12],
                             "status":status,"retry_allowed":False})
    sender=root/SENDER
    guards=set()
    if sender.is_file() and not sender.is_symlink() and sender.stat().st_size<=100000:
        guards=static_guard(sender.read_text(encoding="utf-8"))
    required={"sending_uncertain","no_retry_receipts","exclusive_receipt"}
    return {"schema":"RG_NEWS_PRIVATE_UNCERTAIN_READONLY_V2",
      "confirmed_receipts":counts["PRIVATE_SENT_CONFIRMED"],
      "ambiguous_receipts":counts["UNCERTAIN_NO_RETRY"]+counts["SENDING_UNCERTAIN"],
      "http_rejected_no_retry":counts["HTTP_REJECTED_NO_RETRY"],
      "unsafe_receipts":examples,"no_retry_guard":"SOURCE_VERIFIED" if guards==required else "NOT_VERIFIED",
      "guard_elements_present":sorted(guards),"live_transport_behavior_tested":False,
      "human_delivery_confirmation":"NOT_VERIFIED",
      "read_only":True,"auto_retry_allowed":False,"telegram_api_calls":0,
      "publications":0,"production_writes":0,"public_runner_shutdown_allowed":False}

def selftest():
    sample="""import os
if status == 'SENDING_UNCERTAIN':
 die('PAUSED_UNCERTAIN_DELIVERY_REQUIRES_REVIEW')
if status in ('UNCERTAIN_NO_RETRY','HTTP_REJECTED_NO_RETRY'):
 die('STOP')
fd=os.open(str(receipt),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
"""
    assert static_guard(sample)=={"sending_uncertain","no_retry_receipts","exclusive_receipt"}
    assert static_guard(sample.replace("os.O_EXCL","os.O_TRUNC"))!={"sending_uncertain","no_retry_receipts","exclusive_receipt"}
    print("RG_UNCERTAIN_V2_STATIC_GUARD_SELFTEST_PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=["selftest","inspect"])
    a=parser.parse_args()
    if a.mode=="selftest":selftest()
    else:
        try:print(json.dumps(report(),sort_keys=True,indent=2))
        except (Stop,OSError,ValueError,SyntaxError) as e:
            print(json.dumps({"status":"NOT_VERIFIED","error_class":type(e).__name__,
               "telegram_api_calls":0,"production_writes":0}))
            raise SystemExit(2)
