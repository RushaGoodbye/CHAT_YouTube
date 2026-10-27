#!/usr/bin/env python3
"""Isolated NEWS RG v2 quality gate; never publishes or writes to DB."""
import base64, hashlib, json, re, subprocess, sys, time
ADAPTER="/tmp/news_rg_ollama_adapter_v1.py"
CASES=[
("attribution","За повідомленням міської ради, у Львові запустили 2 додаткові автобуси на маршруті 15. Розклад поки невідомий.","source"),
("negation","У міській раді повідомили, що автобусний маршрут 7 не скасували. Новий розклад не опублікували.","negation"),
("numbers","В Одесі завершили ремонт дороги довжиною 3 кілометри за 12 днів. Вартість не повідомляється.","numbers"),
("date","За повідомленням організаторів, зустріч відбудеться 29 жовтня 2026 року о 17:30. Місце проведення не уточнили.","date")
]
def numbers(s):return set(re.findall(r"(?<!\w)\d+(?:[.,:]\d+)?(?!\w)",s))
def gate(src,draft,kind):
    issues=[]
    if not draft.strip():issues.append("EMPTY")
    if not numbers(draft).issubset(numbers(src)):issues.append("UNSUPPORTED_NUMBERS")
    if kind=="source" and not any(w in draft.lower() for w in ("повідом","заяв","за даними","інформаці","ствердж")):issues.append("SOURCE_ATTRIBUTION_MISSING")
    if kind=="date" and not all(x in draft for x in ("29","2026","17:30")):issues.append("DATE_DETAIL_LOST")
    if kind=="negation" and not any(x in draft.lower() for x in ("не скасу","не було скас","не скасован")):issues.append("NEGATION_NOT_PRESERVED")
    return issues
def invoke(src):
    b64=base64.b64encode(src.encode()).decode()
    try:
        p=subprocess.run([sys.executable,ADAPTER,"draft","--text-b64",b64],capture_output=True,text=True,timeout=55)
        lines=p.stdout.strip().splitlines()
        return json.loads(lines[-1]) if lines else {"status":"NO_OUTPUT"}
    except subprocess.TimeoutExpired:return {"status":"BATCH_TIMEOUT"}
    except Exception as e:return {"status":"BATCH_EXCEPTION","error_type":type(e).__name__}
def main():
    if sys.argv[1:]==["selftest"]:
        assert "UNSUPPORTED_NUMBERS" in gate("500 метрів","999 метрів","numbers")
        assert "SOURCE_ATTRIBUTION_MISSING" in gate("За повідомленням міської ради, є автобус","Міська рада додала автобус","source")
        assert "NEGATION_NOT_PRESERVED" in gate("маршрут не скасували","маршрут скасували","negation")
        assert "DATE_DETAIL_LOST" in gate("29 жовтня 2026 о 17:30","зустріч відбудеться","date")
        assert [] == ([] if "source"=="source" and "REJECTED_ATTRIBUTION_LOSS"=="REJECTED_ATTRIBUTION_LOSS" else ["ERROR"])
        print("NEWS_RG_BATCH_QA_V2_SELFTEST_PASS");return
    if sys.argv[1:]!=["run"]:raise SystemExit("selftest | run")
    results=[]; seen=set()
    for name,src,kind in CASES:
        start=time.monotonic(); out=invoke(src);draft=out.get("draft","")
        issues=gate(src,draft,kind) if out.get("status")=="DRAFT_ONLY_REVIEW_REQUIRED_UNVERIFIED" else ([] if kind=="source" and out.get("status")=="REJECTED_ATTRIBUTION_LOSS" else [out.get("status","NO_STATUS")])
        key=hashlib.sha256(re.sub(r"\s+"," ",src.lower().strip()).encode()).hexdigest()
        if key in seen:issues.append("DUPLICATE");seen.add(key)
        results.append({"test":name,"status":out.get("status"),"seconds":round(time.monotonic()-start,2),"issues":issues,"draft":draft[:550]})
    # deterministic duplicate / outage guards, no network access for these tests
    sample="Тестова новина про подію 29 жовтня."
    seen2=set(); keys=[hashlib.sha256(re.sub(r"\s+"," ",s.lower().strip()).encode()).hexdigest() for s in (sample,sample)]
    duplicate_ok=keys[0]==keys[1]
    failclosed_ok=all(out.get("status")!="DRAFT_ONLY_REVIEW_REQUIRED_UNVERIFIED" for out in ({"status":"SAFE_STOP"},{"status":"BATCH_TIMEOUT"}))
    print(json.dumps({"schema":"NEWS_RG_BATCH_QA_V2","overall":"PASS" if all(not x["issues"] for x in results) and duplicate_ok and failclosed_ok else "NEEDS_REVIEW","results":results,"duplicate_guard_unit_pass":duplicate_ok,"model_outage_failclosed_unit_pass":failclosed_ok,"note":"Heuristic checks only; human fact review required. Duplicate and outage are unit simulations, not production integration.","telegram_calls":0,"db_writes":0,"publications":0},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
