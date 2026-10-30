#!/usr/bin/env python3
"""Classify a stuck RG NEWS2 private-photo send without replaying it.
Read-only on Synology Python 3.8. No production import, Bot API, new poller,
send, scheduled execution, database write or marker cleanup.
"""
import ast
import datetime
import hashlib
import json
import pathlib
import sqlite3
import sys
import tempfile
import time

ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
VAULT=pathlib.Path("/volume1/docker/RG_NAS_MONITOR/news2_private_photo_snapshots")
SRC=ROOT/"operator/rg_news2_outbound_queue_v2.py"
WORKER=ROOT/"telegram_photo_review_flow.py"
DB=ROOT/"news.sqlite3"
MARKER=VAULT/"rg_news2_private_final_unconfirmed_v1.json"
PIN_OUT="e94253084ea2"
PIN_PHOTO="79c473bf774f"
SAFE_FUNCS={"claim_one","deliver_one","record_sent","record_uncertain",
            "send_payload","sendPhoto","photo_auto_gate_open","private_send_only",
            "api","execute","commit","rollback","run","fetchone","fetchall",
            "send","urlopen","request","get","now"}
SAFE_STATES={"awaiting_photo_review","awaiting_moderation","rejected",
             "approved","accepted","sending","sent","uncertain",
             "pending","claimed","ready","photo_reviewed","delivered"}

def name(node):
    if isinstance(node,ast.Name):return node.id
    if isinstance(node,ast.Attribute):return node.attr
    return ""

def parsed(path,pin):
    if not path.is_file() or path.is_symlink():raise RuntimeError("SOURCE_INVALID")
    b=path.read_bytes()
    if hashlib.sha256(b).hexdigest()[:12]!=pin:
        raise RuntimeError("SOURCE_PIN_MISMATCH")
    return ast.parse(b.decode("utf-8"))

def branches(root):
    fns={n.name:n for n in root.body if isinstance(n,ast.FunctionDef)}
    fn=fns.get("run")
    if fn is None:raise RuntimeError("RUN_MISSING")
    guards=[]
    for n in ast.walk(fn):
        if isinstance(n,ast.If) and any(
          isinstance(k,ast.Name) and k.id=="photo_open" for k in ast.walk(n.test)):
            actions=sorted({type(b).__name__ for st in n.body for b in ast.walk(st)
                            if isinstance(b,(ast.Return,ast.Raise,ast.Break,ast.Continue))})
            calls=[{"line":v.lineno,"name":name(v.func)}
                   for st in n.body for v in ast.walk(st)
                   if isinstance(v,ast.Call) and name(v.func) in SAFE_FUNCS]
            guards.append({"line":n.lineno,
                "compare_gte_1":any(isinstance(x,ast.GtE) for x in ast.walk(n.test)) and
                    any(isinstance(x,ast.Constant) and x.value==1
                        for x in ast.walk(n.test)),
                "body_early_exit":("Return" in actions or "Break" in actions),
                "body_actions":actions,"body_safe_calls":calls[:12]})
    calls={key:sorted(x.lineno for x in ast.walk(fn)
                     if isinstance(x,ast.Call) and name(x.func)==key)
           for key in ("deliver_one","send_one","maybe_rss_hourly","private_send_only")}
    assignment=[]
    for n in ast.walk(fn):
        if isinstance(n,(ast.Assign,ast.AnnAssign)):
            targets=n.targets if isinstance(n,ast.Assign) else [n.target]
            if any(isinstance(t,ast.Name) and t.id=="photo_open" for t in targets):
                expr=n.value
                assignment.append({"line":n.lineno,
                    "source_call_names":sorted({name(x.func) for x in ast.walk(expr)
                       if isinstance(x,ast.Call) and name(x.func) in SAFE_FUNCS}),
                    "computed_from_query":any(name(x.func) in ("execute","fetchone","fetchall")
                       for x in ast.walk(expr) if isinstance(x,ast.Call))})
    return {"photo_capacity_guard":guards[:8],
            "dispatch_calls":calls,
            "photo_open_assignment":assignment[:5]}

def worker_flow(root):
    fns={n.name:n for n in root.body if isinstance(n,ast.FunctionDef)}
    result={}
    for label in ("claim_one","deliver_one","send_payload","record_sent","record_uncertain"):
        fn=fns.get(label)
        if fn is None:
            result[label]={"present":False}
            continue
        calls=sorted([{"line":x.lineno,"name":name(x.func)}
                for x in ast.walk(fn) if isinstance(x,ast.Call)
                and name(x.func) in SAFE_FUNCS],key=lambda x:x["line"])
        result[label]={"present":True,"calls":calls[:35],
                        "has_exception_handler":any(isinstance(n,ast.ExceptHandler)
                           for n in ast.walk(fn))}
    return result

def db_report(path):
    if not path.is_file() or path.is_symlink():raise RuntimeError("DB_INVALID")
    conn=sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)
    conn.execute("PRAGMA query_only=ON")
    try:
        tables={x[0] for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"candidates","rg_news2_photo_dispatch"}.issubset(tables):
            raise RuntimeError("DB_SCHEMA_REQUIRED_MISSING")
        info={}
        for name_ in ("candidates","rg_news2_photo_dispatch","rg_v35_photo_audit"):
            if name_ not in tables:continue
            cols={r[1] for r in conn.execute('PRAGMA table_info("'+name_+'")')}
            d={"rows":conn.execute('SELECT COUNT(*) FROM "'+name_+'"').fetchone()[0],
               "columns_present":sorted(x for x in (
                   "candidate_id","created_at","sent_at","updated_at",
                   "telegram_message_id","state","status","photo_reviewed")
                      if x in cols)}
            if name_=="candidates" and "status" in cols:
                d["photo_pending"]=conn.execute(
                  "SELECT COUNT(*) FROM candidates WHERE status='awaiting_photo_review'").fetchone()[0]
            if name_=="rg_news2_photo_dispatch":
                if "telegram_message_id" in cols:
                    d["receipts"]=conn.execute(
                      "SELECT COUNT(*) FROM rg_news2_photo_dispatch WHERE telegram_message_id IS NOT NULL").fetchone()[0]
                    d["without_receipt"]=conn.execute(
                      "SELECT COUNT(*) FROM rg_news2_photo_dispatch WHERE telegram_message_id IS NULL").fetchone()[0]
                if "state" in cols:
                    states=conn.execute("SELECT state,COUNT(*) FROM rg_news2_photo_dispatch GROUP BY state").fetchall()
                    d["state_counts"]={state if state in SAFE_STATES else "other_redacted":count
                            for state,count in states}
                key="candidate_id" if "candidate_id" in cols else None
                cand_cols={r[1] for r in conn.execute('PRAGMA table_info("candidates")')}
                if key and {"id","photo_reviewed"}.issubset(cand_cols):
                    d["outstanding_photo_cards"]=conn.execute(
                        "SELECT COUNT(*) FROM rg_news2_photo_dispatch d "
                        "JOIN candidates c ON c.id=d.candidate_id "
                        "WHERE d.telegram_message_id IS NOT NULL AND COALESCE(c.photo_reviewed,0)=0"
                    ).fetchone()[0]
            info[name_]=d
        return info
    finally:
        conn.close()

def marker_report(path):
    if path.is_symlink():raise RuntimeError("MARKER_SYMLINK_INVALID")
    if not path.is_file():return {"present":False}
    if path.stat().st_size>4096:raise RuntimeError("MARKER_TOO_LARGE")
    state=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state,dict):raise RuntimeError("MARKER_FORMAT_INVALID")
    marker_state=state.get("state")
    out={"present":True,"expected_uncertain_state":
         marker_state=="SEND_ATTEMPTED_REQUIRES_RECEIPT",
         "age_minutes":round(max(0,time.time()-path.stat().st_mtime)/60,1)}
    return out

def inspect(root=ROOT,vault=VAULT,po=PIN_OUT,pp=PIN_PHOTO):
    out=branches(parsed(root/"operator/rg_news2_outbound_queue_v2.py",po))
    flow=worker_flow(parsed(root/"telegram_photo_review_flow.py",pp))
    db=db_report(root/"news.sqlite3")
    mark=marker_report(vault/"rg_news2_private_final_unconfirmed_v1.json")
    receipts=db["rg_news2_photo_dispatch"].get("receipts")
    open_cards=db["rg_news2_photo_dispatch"].get("outstanding_photo_cards")
    no_extra_claims=db["rg_news2_photo_dispatch"].get("without_receipt")==0
    expected_guard=any(g["compare_gte_1"] and g["body_early_exit"]
                       for g in out["photo_capacity_guard"])
    evidence={"schema":"RG_NEWS2_STALLED_SEND_RECONCILE_V1",
      "read_only":True,"telegram_calls":0,"database_writes":0,
      "marker_changes":0,"publications":0,"new_pollers":0,
      "uncertainty":mark,"database":db,"installed_outbound_control_flow":out,
      "installed_worker_call_flow":flow,
      "analysis":{
        "confirmed_receipts":receipts,
        "open_cards":open_cards,
        "all_dispatch_rows_have_receipts":no_extra_claims,
        "capacity_guard_exits_without_dispatch":expected_guard,
        "likely_reason":"PREVIOUS_PHOTO_CARD_NOT_REVIEWED" if
          open_cards and expected_guard else "NOT_YET_PROVEN",
        "automatic_uncertainty_marker_clear_safe":False,
        "next_action":"DO_NOT_RETRY_UNTIL_MARKER_ATTEMPT_RECONCILED"}}
    return evidence

def selftest():
    with tempfile.TemporaryDirectory() as td:
        root=pathlib.Path(td)/"nas"
        (root/"operator").mkdir(parents=True)
        vault=pathlib.Path(td)/"vault";vault.mkdir()
        (root/"operator/rg_news2_outbound_queue_v2.py").write_text(
           "def run(mode):\n"
           "  if photo_open>=1:return 'BLOCKED'\n"
           "  deliver_one()\n")
        (root/"telegram_photo_review_flow.py").write_text(
           "def claim_one():\n  return None\n"
           "def deliver_one():\n  claim_one()\n  send_payload()\n  record_sent()\n"
           "def send_payload():\n  return 1\n"
           "def record_sent():\n  return 1\n"
           "def record_uncertain():\n  return 0\n")
        c=sqlite3.connect(str(root/"news.sqlite3"))
        c.execute("CREATE TABLE candidates(id INT,status TEXT,photo_reviewed INT)")
        c.execute("INSERT INTO candidates VALUES(1,'awaiting_photo_review',0)")
        c.execute("CREATE TABLE rg_news2_photo_dispatch(candidate_id INT, telegram_message_id INT)")
        c.execute("INSERT INTO rg_news2_photo_dispatch VALUES(1,123)")
        c.commit();c.close()
        (vault/"rg_news2_private_final_unconfirmed_v1.json").write_text(
           '{"state":"SEND_ATTEMPTED_REQUIRES_RECEIPT"}')
        def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        r=inspect(root,vault,sha(root/"operator/rg_news2_outbound_queue_v2.py"),
                  sha(root/"telegram_photo_review_flow.py"))
        assert r["analysis"]["capacity_guard_exits_without_dispatch"]
        assert r["analysis"]["open_cards"]==1
        assert r["analysis"]["automatic_uncertainty_marker_clear_safe"] is False
        assert r["uncertainty"]["present"]
        assert r["analysis"]["confirmed_receipts"]==1
    print("RG_NEWS2_STALLED_SEND_RECONCILE_V1_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["inspect"]:
        print(json.dumps(inspect(),indent=2,sort_keys=True,ensure_ascii=False))
    else:sys.exit("Only selftest or inspect supported")
