#!/usr/bin/env python3
"""NEWS RG private-review integration: isolated staging, never alters NEWS2 delivery.

Commands: selftest, preflight, prepare-one.
No Bot API, no polling, no public posting. 'prepare-one' stores a review-required
sidecar in a private operator directory; NEVER writes to production databases.
"""
import base64,hashlib,json,os,pathlib,re,sqlite3,subprocess,sys,tempfile,time,fcntl,urllib.request,urllib.parse
ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
OP=ROOT/"operator"
SHADOW=OP/"news_rg_editorial_shadow_v1.sqlite3"
PROD=ROOT/"news.sqlite3"
HANDLER=ROOT/"telegram_photo_review_flow.py"
ADAPTER=pathlib.Path("/tmp/news_rg_ollama_adapter_v1.py")
OUT=OP/"news_rg_private_review_staging"
def atomic(path,obj):
    data=json.dumps(obj,ensure_ascii=False,indent=2).encode("utf-8")
    fd,name=tempfile.mkstemp(prefix=".newsrg_",dir=str(path.parent))
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"wb") as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
def ro(path):
    if not path.is_file() or path.is_symlink():raise RuntimeError("SOURCE_MISSING_OR_SYMLINK")
    db=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=5)
    db.execute("PRAGMA query_only=ON")
    return db
def tables(c):
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
def preflight():
    a=ro(SHADOW);b=ro(PROD)
    try:
        sh=tables(a);pr=tables(b)
        if not {"story_shadow","editorial_draft"}.issubset(sh) or not {"candidates","rg_news2_photo_dispatch"}.issubset(pr):
            raise RuntimeError("SCHEMA_MISMATCH")
        counts=dict(a.execute("SELECT status,COUNT(*) FROM story_shadow GROUP BY status"))
        matching=b.execute("SELECT count(*) FROM candidates WHERE status='awaiting_photo_review'").fetchone()[0]
        return {"status":"READY_FOR_ISOLATED_PREPARE","shadow_status_counts":counts,
                "main_awaiting_photo_review":matching,
                "existing_photo_handler_present":HANDLER.is_file(),
                "adapter_present":ADAPTER.is_file(),
                "photo_button_meaning":"PHOTO_ONLY_NOT_EDITORIAL_APPROVAL",
                "private_delivery":"NOT_CONNECTED","publications":0,"telegram_calls":0,"production_db_writes":0}
    finally:a.close();b.close()
def clean(s):
    s=re.sub(r"\s*(?:🇺🇦\s*)?(?:УС\s*/\s*Підписатися|Підписатися\s*на\s*канал)\s*$","",s,flags=re.I).strip()
    s=re.sub(r"\s*(?:🇺🇦\s*)?INSIDER\s*UA\s*\|\s*Прислати\s*контент\s*$","",s,flags=re.I).strip()
    return s
def prepare_one():
    check=preflight()
    if not ADAPTER.is_file():raise RuntimeError("OLLAMA_ADAPTER_MISSING")
    c=ro(SHADOW)
    try:
        rows=c.execute("""SELECT key,text,media_url,posted_at,channel
          FROM story_shadow WHERE status='needs_editorial_rewrite'
          AND length(text)>=100 AND media_url LIKE 'https://%'
          ORDER BY posted_at DESC LIMIT 100""").fetchall()
    finally:c.close()
    if OUT.is_symlink():raise RuntimeError("OUTBOX_SYMLINK")
    OUT.mkdir(mode=0o700,exist_ok=True)
    os.chmod(OUT,0o700)
    existing_v1=OP/"news_rg_private_pilot_claim_v1.json"
    reserved=set()
    if existing_v1.is_file() and not existing_v1.is_symlink():
        try:reserved.add(json.loads(existing_v1.read_text()).get("draft_id"))
        except (OSError,ValueError):raise RuntimeError("UNCERTAIN_V1_RECEIPT_UNREADABLE")
    receipts=OP/"news_rg_private_delivery_v2"
    if receipts.is_dir():
        reserved.update(p.stem for p in receipts.glob("*.json"))
    tested=0; rejected=0; failures={}
    for key,source,photo,posted,channel in rows:
        digest=hashlib.sha256(str(key).encode()).hexdigest()[:24]
        if digest in reserved or (OUT/(digest+".json")).exists():continue
        if tested>=3:break
        tested+=1
        url=urllib.parse.urlsplit(photo)
        if url.scheme!="https" or url.hostname not in ("cdn1.telesco.pe","cdn2.telesco.pe","cdn3.telesco.pe","cdn4.telesco.pe","cdn5.telesco.pe"):
            rejected+=1;failures["UNTRUSTED_MEDIA_HOST"]=failures.get("UNTRUSTED_MEDIA_HOST",0)+1;continue
        try:
            req=urllib.request.Request(photo,method="HEAD",headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req,timeout=8) as res:
                mime=res.headers.get("Content-Type","").split(";")[0].strip().lower()
            if mime not in ("image/jpeg","image/png","image/webp"):
                rejected+=1;failures["NOT_PHOTO"]=failures.get("NOT_PHOTO",0)+1;continue
        except Exception:
            rejected+=1;failures["MEDIA_UNVERIFIED"]=failures.get("MEDIA_UNVERIFIED",0)+1;continue
        source=clean(source)
        cmd=[sys.executable,str(ADAPTER),"draft","--text-b64",base64.b64encode(source.encode()).decode()]
        try:proc=subprocess.run(cmd,capture_output=True,text=True,timeout=50)
        except subprocess.TimeoutExpired:
            rejected+=1;failures["ADAPTER_TIMEOUT"]=failures.get("ADAPTER_TIMEOUT",0)+1;continue
        if proc.returncode:
            rejected+=1;failures["ADAPTER_FAILED"]=failures.get("ADAPTER_FAILED",0)+1;continue
        try:response=json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError,IndexError):
            rejected+=1;failures["ADAPTER_BAD_RESULT"]=failures.get("ADAPTER_BAD_RESULT",0)+1;continue
        draft=clean(response.get("draft",""))
        if response.get("status")!="DRAFT_ONLY_REVIEW_REQUIRED_UNVERIFIED" or not (60<=len(draft)<=900) or "НЕВДАЛО" in draft.upper() or re.search(r"[ыъэёЫЪЭЁ]",draft):
            rejected+=1;failures["BAD_DRAFT"]=failures.get("BAD_DRAFT",0)+1;continue
        target=OUT/(digest+".json")
        data={"schema":"NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1","draft_id":digest,
              "source_key":key,"channel":channel,"posted_at":posted,"media_url":photo,
              "original_text":source,"proposed_text":draft,"editorial_status":"HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED",
              "photo_approval_is_not_editorial_approval":True,"telegram_delivery":"NOT_SENT",
              "public_publication":"OFF","prepared_at":int(time.time())}
        atomic(target,data)
        return {"status":"ISOLATED_DRAFT_STAGED","draft_id":digest,"source_channel":channel,
                "source_length":len(source),"draft_length":len(draft),"verified_media_mime":mime,
                "candidates_examined":tested,"candidates_rejected":rejected,"human_fact_review_required":True,
                "private_delivery":"NOT_CONNECTED","draft_preview":draft[:900],
                "production_db_writes":0,"telegram_calls":0,"publications":0}
    return {"status":"NO_VALID_DRAFT_IN_BATCH","candidates_examined":tested,
            "candidates_rejected":rejected,"reasons":failures,"publications":0,"telegram_calls":0}
def main():
    try:
        if sys.argv[1:]==["selftest"]:
            assert clean("Новина 🇺🇦 УС / Підписатися")=="Новина"
            assert clean("Новина 🇺🇦 INSIDER UA | Прислати контент")=="Новина"
            print("NEWS_RG_PRIVATE_BRIDGE_SELFTEST_PASS")
        elif sys.argv[1:]==["preflight"]:print(json.dumps(preflight(),ensure_ascii=False,indent=2))
        elif sys.argv[1:]==["prepare-one"]:print(json.dumps(prepare_one(),ensure_ascii=False,indent=2))
        else:raise RuntimeError("COMMAND_NOT_ALLOWED")
    except Exception as e:
        print(json.dumps({"status":"SAFE_STOP","error_class":str(e) if isinstance(e,RuntimeError) else type(e).__name__,
                          "telegram_calls":0,"publications":0},ensure_ascii=False))
        sys.exit(2)
if __name__=="__main__":main()
