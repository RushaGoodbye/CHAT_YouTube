#!/usr/bin/env python3
"""NEWS RG bounded AI editorial of ISOLATED shadow Telegram news only.

Never touches production news.sqlite3, existing bot, callback, scheduler,
Telegram API or public channels. Requires explicit NEWS_RG_AI_ALLOWED=1 to
spend provider quota; otherwise audit/rewriter returns no-budget-used.
"""
import datetime as dt
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE=pathlib.Path(__file__).resolve().parent
SHADOW=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2/operator/news_rg_editorial_shadow_v1.sqlite3")
MODEL_DEFAULT="gemini-3.5-flash-lite"
MAX_AI_REQUESTS_PER_RUN=3
MAX_AI_RESERVATIONS_ROLLING_24H=10
MAX_AGE_SECONDS=4*3600
POLICY_FILENAME="news_rg_editorial_contract_v1.py"

def policy():
    file=HERE/POLICY_FILENAME
    if not file.is_file():raise RuntimeError("EDITORIAL_POLICY_FILE_MISSING")
    spec=importlib.util.spec_from_file_location("news_rg_editorial_policy",str(file))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def facts_supported(original,headline,body):
    nums=lambda s:set(re.findall(r"\d+(?:[.,]\d+)?",s or ""))
    return not (nums(headline+" "+body)-nums(original))

def eligible(cx,now,limit):
    return cx.execute("""SELECT s.key,s.channel,s.text,s.posted_at,s.media_url,
           s.media_type FROM story_shadow s LEFT JOIN editorial_draft d
           ON d.key=s.key WHERE s.status='needs_editorial_rewrite'
           AND d.key IS NULL AND s.posted_at>=? AND s.posted_at<=?
           ORDER BY s.posted_at DESC LIMIT ?""",
           (now-MAX_AGE_SECONDS,now+300,limit)).fetchall()

def gemini_api(text,model,api_key):
    if not re.fullmatch(r"gemini-[0-9a-zA-Z_.-]{4,60}",model):
        raise RuntimeError("AI_MODEL_NAME_INVALID")
    payload={"contents":[{"role":"user","parts":[{"text":text}]}],
        "generationConfig":{
           "responseMimeType":"application/json",
           "responseSchema":{
               "type":"OBJECT",
               "properties":{
                   "relevant":{"type":"BOOLEAN"},
                   "is_ad":{"type":"BOOLEAN"},
                   "headline":{"type":"STRING"},
                   "body":{"type":"STRING"}},
               "required":["relevant","is_ad","headline","body"],
               "propertyOrdering":["relevant","is_ad","headline","body"]},
           "temperature":0.2,"maxOutputTokens":1800}}
    url="https://generativelanguage.googleapis.com/v1beta/models/"+model+":generateContent"
    req=urllib.request.Request(url,data=json.dumps(payload).encode("utf-8"),
             headers={"Content-Type":"application/json","x-goog-api-key":api_key},
             method="POST")
    try:
        with urllib.request.urlopen(req,timeout=25) as resp:
            raw=resp.read(180000)
    except urllib.error.HTTPError as err:
        if err.code in (400,403,404):raise RuntimeError("AI_MODEL_OR_ACCESS_INVALID")
        if err.code==429:raise RuntimeError("AI_RATE_LIMIT_COOLDOWN")
        raise RuntimeError("AI_PROVIDER_HTTP_ERROR")
    except (urllib.error.URLError,TimeoutError,OSError):
        raise RuntimeError("AI_PROVIDER_CONNECTION_ERROR")
    try:
        data=json.loads(raw.decode("utf-8"))
        parts=data["candidates"][0]["content"]["parts"]
        value="".join(x.get("text","") for x in parts if isinstance(x,dict))
        result=json.loads(value)
        if not isinstance(result,dict):raise ValueError("not a dictionary")
        return result
    except (ValueError,IndexError,KeyError,TypeError,UnicodeError):
        raise RuntimeError("AI_RESPONSE_INVALID")

def validate_candidate(editorial,source,media_url,policy_module):
    if not isinstance(editorial,dict) or not editorial.get("relevant") or editorial.get("is_ad"):
        return "IRRELEVANT_OR_ADVERTISEMENT"
    headline=editorial.get("headline","")
    body=editorial.get("body","")
    if not isinstance(headline,str) or not isinstance(body,str):
        return "EDITORIAL_RESPONSE_FIELDS_INVALID"
    if not facts_supported(source,headline,body):
        return "UNSUPPORTED_NUMERIC_FACTS"
    report=policy_module.validate_editorial(headline,body,media_url)
    if not report["editorial_format_ready"]:
        return "EDITORIAL_FORMAT_FAILED"
    # No source attribution or external URLs is allowed in the public draft.
    return None

def reserve_ai_budget(cx,key,now):
    # This guard is conservative: an attempted request consumes one unit,
    # even if the provider fails. Quota cannot be bypassed by concurrent runs.
    cx.execute("BEGIN IMMEDIATE")
    try:
        cx.execute("CREATE TABLE IF NOT EXISTS editorial_ai_budget(" 
                   "story_key TEXT PRIMARY KEY, attempted_at INTEGER NOT NULL)")
        count=cx.execute("SELECT COUNT(*) FROM editorial_ai_budget "
                         "WHERE attempted_at>=?",(now-86400,)).fetchone()[0]
        already=cx.execute("SELECT 1 FROM editorial_ai_budget WHERE story_key=?",
                           (key,)).fetchone()
        if already or count>=MAX_AI_RESERVATIONS_ROLLING_24H:
            cx.execute("ROLLBACK")
            return False
        cx.execute("INSERT INTO editorial_ai_budget VALUES(?,?)",(key,now))
        cx.execute("COMMIT")
        return True
    except Exception:
        cx.execute("ROLLBACK")
        raise

def run(store=SHADOW,max_items=MAX_AI_REQUESTS_PER_RUN,provider=None,
        allowed=None,model=None):
    pol=policy()
    if max_items<1 or max_items>MAX_AI_REQUESTS_PER_RUN:
        raise RuntimeError("AI_REQUEST_CAP_INVALID")
    allowed=(os.getenv("NEWS_RG_AI_ALLOWED")=="1") if allowed is None else allowed
    model=model or os.getenv("NEWS_RG_GEMINI_MODEL",MODEL_DEFAULT)
    api_key=os.getenv("GEMINI_API_KEY","")
    if provider is None and (not allowed or not api_key):
        return {"schema":"NEWS_RG_EDITORIAL_SHADOW_V1",
            "status":"NO_AI_BUDGET_USED",
            "reason":"PROVIDER_NOT_AUTHORIZED_OR_UNAVAILABLE",
            "pending_rewrites_not_changed":True,"telegram_calls":0,
            "publications":0,"private_sends":0,"ai_requests":0}
    if store.is_symlink() or not store.is_file():
        raise RuntimeError("SHADOW_DB_MISSING")
    now=int(time.time())
    cx=sqlite3.connect(str(store),timeout=8,isolation_level=None)
    cx.execute("PRAGMA busy_timeout=8000")
    results={"schema":"NEWS_RG_EDITORIAL_SHADOW_V1","status":"SHADOW_EDITORIAL_RUN",
             "ai_requests":0,"drafts_ready_for_manual_review":0,
             "skipped_and_unpublished":0,"provider_deferrals":0,
             "ai_budget_limit_rolling_24h":MAX_AI_RESERVATIONS_ROLLING_24H,
             "ai_budget_guard_blocked":False,
             "telegram_calls":0,"publications":0,"private_sends":0}
    try:
        items=eligible(cx,now,max_items)
        for key,channel,source,posted,media,media_type in items:
            if not reserve_ai_budget(cx,key,now):
                results["ai_budget_guard_blocked"]=True
                break
            prompt=pol.rewrite_instructions(source)
            try:
                response=(provider(prompt) if provider is not None else
                          gemini_api(prompt,model,api_key))
                results["ai_requests"]+=1
            except RuntimeError as e:
                results["provider_deferrals"]+=1
                results["reason_code"]=str(e) if str(e).isupper() else "AI_DEFER"
                break
            issue=validate_candidate(response,source,media,pol)
            if issue is not None:
                # Preserve source pending; no automatic retries this minute.
                results["skipped_and_unpublished"]+=1
                continue
            headline=pol.clean_news_text(response["headline"])
            body=pol.clean_news_text(response["body"])
            digest=hashlib.sha256((headline+"\n"+body).encode("utf-8")).hexdigest()
            cx.execute("BEGIN IMMEDIATE")
            try:
                existing=cx.execute("SELECT status FROM story_shadow WHERE key=?",
                                    (key,)).fetchone()
                if existing is None or existing[0]!="needs_editorial_rewrite":
                    cx.execute("ROLLBACK")
                    continue
                cx.execute("""INSERT OR IGNORE INTO editorial_draft
                              (key,headline,body,validated_at)
                              VALUES(?,?,?,?)""",(key,headline,body,now))
                cx.execute("""UPDATE story_shadow SET status='editorial_ready'
                              WHERE key=? AND status='needs_editorial_rewrite'""",
                           (key,))
                cx.execute("COMMIT")
            except Exception:
                cx.execute("ROLLBACK")
                raise
            results["drafts_ready_for_manual_review"]+=1
        return results
    finally:cx.close()

def selftest():
    pol=policy()
    title="Новина про важливу подію в україні"
    original=("Оприлюднено повідомлення про актуальну подію. "
              "Обставини вивчають уповноважені служби. ")*12
    body=("Відповідальні служби уточнюють інформацію про подію. "
          "Перевірка обставин триває. ")*10
    body=body[:770].rstrip(" ,.")+"."
    good={"headline":title,"body":body,"relevant":True,"is_ad":False}
    assert validate_candidate(good,original,"https://cdn.example.net/a.jpg",pol) is None
    bad=dict(good,body=body+" Кількість постраждалих 999.")
    assert validate_candidate(bad,original,"https://cdn.example.net/a.jpg",pol)=="UNSUPPORTED_NUMERIC_FACTS"
    with tempfile.TemporaryDirectory() as td:
        db=pathlib.Path(td)/"editorial.sqlite3"
        cx=sqlite3.connect(str(db))
        cx.executescript("""CREATE TABLE story_shadow (
            key TEXT PRIMARY KEY, channel TEXT, text TEXT, posted_at INT,
            media_url TEXT, media_type TEXT, status TEXT);
            CREATE TABLE editorial_draft (
            key TEXT PRIMARY KEY, headline TEXT,body TEXT,validated_at INT)""")
        cx.execute("INSERT INTO story_shadow VALUES(?,?,?,?,?,?,?)",
                   ("one","Ateobreaking",original,int(time.time())-100,
                    "https://cdn.example.net/a.jpg","photo","needs_editorial_rewrite"))
        cx.commit();cx.close()
        r=run(db,provider=lambda _:good,allowed=True)
        assert r["drafts_ready_for_manual_review"]==1,r
        q=run(db,provider=lambda _:good,allowed=True)
        assert q["drafts_ready_for_manual_review"]==0,q
        cx=sqlite3.connect(str(db))
        assert cx.execute("SELECT status FROM story_shadow").fetchone()[0]=="editorial_ready"
        cx.close()
    print("NEWS_RG_EDITORIAL_SHADOW_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["rewrite"]:
        print(json.dumps(run(),sort_keys=True,ensure_ascii=False,indent=2))
    else:raise SystemExit("Only selftest or rewrite supported")
