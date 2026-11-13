#!/usr/bin/env python3
"""Read-only private send uncertainty audit; never retry/ack or expose draft IDs."""
import argparse,hashlib,json,os,sys
from collections import Counter
from pathlib import Path

ROOT=Path("/volume1/docker/RG_TELEGRAM_NEWS_2/operator")
RECEIPTS=ROOT/"news_rg_private_multipart_receipts_v1"
SENDER=ROOT/"news_rg_durable_private_sender_v1.py"
UNSAFE={"UNCERTAIN_NO_RETRY","SENDING_UNCERTAIN","HTTP_REJECTED_NO_RETRY"}
GOOD={"PRIVATE_SENT_CONFIRMED"}
class Stop(ValueError):pass

def inspect(root=ROOT):
    d=root/"news_rg_private_multipart_receipts_v1"
    if not d.is_dir() or d.is_symlink():raise Stop("RECEIPT_DIR_UNAVAILABLE")
    counts=Counter();uncertain=[]
    for p in sorted(d.glob("*.json")):
        if p.is_symlink() or not p.is_file() or p.stat().st_size>20000:
            raise Stop("UNSAFE_RECEIPT_FILE")
        info=json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(info,dict):raise Stop("BAD_RECEIPT")
        state=info.get("status")
        if not isinstance(state,str) or len(state)>55:raise Stop("BAD_RECEIPT_STATUS")
        counts[state]+=1
        if state in UNSAFE:
            uncertain.append({"receipt_ref":hashlib.sha256(p.name.encode()).hexdigest()[:12],
             "status":state,"error_class":str(info.get("error_class","UNSPECIFIED"))[:40],
             "auto_retry_permitted":False})
    source=root/"news_rg_durable_private_sender_v1.py"
    guard="NOT_VERIFIED"
    if source.is_file() and not source.is_symlink() and source.stat().st_size<=100000:
        text=source.read_text(encoding="utf-8")
        if ("PAUSED_UNCERTAIN_DELIVERY_REQUIRES_REVIEW" in text and
            "UNCERTAIN_NO_RETRY" in text and
            "os.O_CREAT|os.O_EXCL" in text and
            "if status in ('SENDING_UNCERTAIN','UNCERTAIN_NO_RETRY')" in text):
            guard="GUARD_PRESENT_SOURCE_ONLY"
    return {"schema":"RG_NEWS_PRIVATE_UNCERTAIN_READONLY_V1",
       "read_only":True,"receipt_counts":dict(counts),
       "uncertain_receipts":uncertain,
       "uncertain_count":len(uncertain),
       "at_most_once_sender_guard":guard,
       "auto_retry_unsafe_receipts":False,"clear_uncertain_receipts":False,
       "human_delivery_confirmation":"NOT_VERIFIED",
       "telegram_api_calls":0,"publications":0,"production_writes":0,
       "public_runner_shutdown_allowed":False}

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        root=Path(t);(root/"news_rg_private_multipart_receipts_v1").mkdir()
        (root/"news_rg_private_multipart_receipts_v1"/"x.json").write_text(
           '{"status":"UNCERTAIN_NO_RETRY","error_class":"URLError"}')
        result=inspect(root)
        assert result["uncertain_count"]==1
        assert result["uncertain_receipts"][0]["auto_retry_permitted"] is False
        assert "x.json" not in json.dumps(result)
    print("PRIVATE_UNCERTAIN_NO_RETRY_AUDIT_SELFTEST_PASS")
    print("TELEGRAM_DELIVERY_NOT_RETRIED_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("mode",choices=["selftest","inspect"])
    a=p.parse_args()
    if a.mode=="selftest":selftest();sys.exit(0)
    try:print(json.dumps(inspect(),ensure_ascii=False,sort_keys=True,indent=2))
    except (Stop,ValueError,OSError) as e:
        print(json.dumps({"status":"NOT_VERIFIED","reason":type(e).__name__,
          "telegram_api_calls":0,"production_writes":0}))
        sys.exit(2)
