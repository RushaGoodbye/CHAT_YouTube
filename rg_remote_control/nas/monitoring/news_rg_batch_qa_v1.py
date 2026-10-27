#!/usr/bin/env python3
"""NEWS RG dry-run quality batch. No Telegram or DB access."""
import base64, json, pathlib, re, subprocess, sys, time
ADAPTER = "/tmp/news_rg_ollama_adapter_v1.py"
CASES = [
 ("empty_marker","TEST_NEWS",False),
 ("kyiv_space","У Києві відкрили новий громадський простір площею 500 квадратних метрів. Дата відкриття не повідомляється.",True),
 ("odessa_road","В Одесі завершили ремонт дороги довжиною 3 кілометри. Роботи тривали 12 днів. Вартість проєкту не повідомляється.",True),
 ("attributed","За повідомленням міської ради, у Львові запустили 2 додаткові автобуси на маршруті 15. Інформація про розклад відсутня.",True),
]
def validate(source, expected, out):
    status=out.get("status")
    if not expected:
        return status=="REJECTED_INSUFFICIENT_FACTS" and out.get("publications")==0
    if status!="DRAFT_ONLY_REVIEW_REQUIRED_UNVERIFIED": return False
    draft=out.get("draft","")
    if not isinstance(draft,str) or len(draft)<15: return False
    nums=lambda s:set(re.findall(r"\b\d+(?:[.,]\d+)?\b",s))
    return nums(draft).issubset(nums(source)) and all(out.get(x)==0 for x in ("publications","db_writes","telegram_calls"))
def main():
    if sys.argv[1:]==["selftest"]:
        assert len(CASES)==4
        assert validate("TEST_NEWS",False,{"status":"REJECTED_INSUFFICIENT_FACTS","publications":0})
        assert not validate("500 метрів",True,{"status":"DRAFT_ONLY_REVIEW_REQUIRED_UNVERIFIED","draft":"Новий простір 999 метрів","publications":0,"db_writes":0,"telegram_calls":0})
        print("NEWS_RG_BATCH_QA_SELFTEST_PASS");return
    if sys.argv[1:]!=["run"]:raise SystemExit("Usage: selftest | run")
    if not pathlib.Path(ADAPTER).is_file():raise SystemExit("ADAPTER_MISSING")
    tests=[]
    for name,source,expected in CASES:
        start=time.monotonic()
        try:
            encoded=base64.b64encode(source.encode("utf-8")).decode("ascii")
            p=subprocess.run([sys.executable,ADAPTER,"draft","--text-b64",encoded],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",timeout=55)
            out=json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
            code=p.returncode
        except subprocess.TimeoutExpired:
            out={"status":"BATCH_TIMEOUT"};code=-1
        except Exception as exc:
            out={"status":"BATCH_ERROR","error_type":type(exc).__name__};code=-2
        tests.append({"name":name,"pass":validate(source,expected,out),"seconds":round(time.monotonic()-start,2),"status":out.get("status"),"draft":out.get("draft","")[:700],"exit_code":code})
    print(json.dumps({"schema":"NEWS_RG_BATCH_QA_V1","overall":"PASS" if all(t["pass"] for t in tests) else "NEEDS_REVIEW","tests":tests,"telegram_calls":0,"db_writes":0,"publications":0},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
