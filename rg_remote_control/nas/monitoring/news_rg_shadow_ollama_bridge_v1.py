#!/usr/bin/env python3
"""NEWS RG today bridge: safe operator preview from existing editorial shadow; no DB writes."""
import base64, json, pathlib, sqlite3, subprocess, sys, time
DB=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2/operator/news_rg_editorial_shadow_v1.sqlite3")
ADAPTER="/tmp/news_rg_ollama_adapter_v1.py"
def report():
    try:
        if DB.is_symlink():return {"status":"SHADOW_SYMLINK_STOP"}
        if not DB.is_file():return {"status":"SHADOW_MISSING"}
    except PermissionError:
        return {"status":"SHADOW_PERMISSION_DENIED"}
    con=sqlite3.connect(DB.as_uri()+"?mode=ro",uri=True,timeout=5)
    try:
        con.execute("PRAGMA query_only=ON")
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"story_shadow","editorial_draft"}.issubset(tables):return {"status":"SCHEMA_MISMATCH","tables_present":sorted(tables)}
        counts={r[0]:r[1] for r in con.execute("SELECT status,COUNT(*) FROM story_shadow GROUP BY status")}
        row=con.execute("SELECT key,text,media_url,status,posted_at FROM story_shadow WHERE status='needs_editorial_rewrite' AND length(text)>90 ORDER BY posted_at DESC LIMIT 1").fetchone()
        return {"status":"READY" if row else "NO_ELIGIBLE_STORY","counts":counts,"sample":row}
    finally:con.close()
def main():
    mode=sys.argv[1] if len(sys.argv)>1 else "inspect"
    if mode=="selftest":
        assert base64.b64decode(base64.b64encode("Київ".encode())).decode()=="Київ"
        print("NEWS_RG_SHADOW_OLLAMA_BRIDGE_SELFTEST_PASS");return
    if mode not in ("inspect","one-draft"):raise SystemExit("selftest|inspect|one-draft")
    data=report(); row=data.pop("sample",None)
    output={"schema":"NEWS_RG_SHADOW_OLLAMA_BRIDGE_V1","status":data["status"],"queue_counts":data.get("counts",{}),"db_writes":0,"telegram_calls":0,"publications":0}
    if row:
        key,source,media,status,posted=row
        output["candidate"]={"key_digest":__import__("hashlib").sha256(str(key).encode()).hexdigest()[:12],"source_length":len(source),"media_present":bool(media),"posted_at":posted}
    if mode=="one-draft" and row:
        encoded=base64.b64encode(source[:10000].encode()).decode()
        try:
            result=subprocess.run([sys.executable,ADAPTER,"draft","--text-b64",encoded],capture_output=True,text=True,timeout=60)
            parsed=json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {}
        except (Exception,) as exc:
            parsed={"status":"BRIDGE_SAFE_STOP","reason":type(exc).__name__}
        output["status"]=parsed.get("status","UNKNOWN")
        if output["status"]=="DRAFT_ONLY_REVIEW_REQUIRED_UNVERIFIED":
            output["draft"]=parsed.get("draft","")
            output["source_excerpt"]=source[:1000]
            output["review_required"]=True
        else:output["reason"]=parsed.get("reason",parsed.get("error_type","GENERATION_NOT_READY"))
    print(json.dumps(output,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
