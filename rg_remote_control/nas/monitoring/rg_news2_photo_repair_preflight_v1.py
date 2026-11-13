#!/usr/bin/env python3
"""NEWS2 photo delivery preflight. Read-only, safe aggregate output, Python 3.8+."""
import ast
import json
import pathlib
import re
import sqlite3
import sys
import time

ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
FILES=("rg_news_dsm_tick.sh","operator/rg_news2_outbound_queue_v2.py",
       "telegram_photo_review_flow.py","operator/rg_news2_rss_hourly.py",
       "operator/rg_news2_p31_guarded_callback_once.py")
NAMES=("claim_one","deliver_one","record_sent","record_uncertain","send_payload",
       "handle_callback","init_outbox","validate_photo")
STATES=("awaiting_photo_review","awaiting_moderation","photo_reviewed")
SCRIPT_REF=re.compile(r"(?<![A-Za-z0-9_.-])([A-Za-z][A-Za-z0-9_.-]{1,90}\.(?:sh|py))(?![A-Za-z0-9_.-])")
SAFE_STATES={"pending","ready","queued","sent","failed","retry","rejected",
             "approved","done","delivered","staged","uncertain","processing",
             "reserved","claimed","inflight","held","blocked","deferred",
             "created","awaiting_photo_review","awaiting_moderation"}

def python_file(path,rel):
    out={"file":rel,"present":False}
    if not path.is_file() or path.is_symlink() or path.stat().st_size>800000:
        return out
    try:
        source=path.read_text(encoding="utf-8",errors="replace")
        tree=ast.parse(source)
        out["present"]=True
        out["syntax"]="PASS"
        out["age_hours"]=max(0,round((time.time()-path.stat().st_mtime)/3600,1))
        out["definitions"]={n.name:{"args":len(n.args.posonlyargs)+len(n.args.args),
                                     "defaults":len(n.args.defaults)}
            for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in NAMES}
        calls={}
        for n in ast.walk(tree):
            if not isinstance(n,ast.Call):continue
            fn=n.func
            name=fn.id if isinstance(fn,ast.Name) else (fn.attr if isinstance(fn,ast.Attribute) else "")
            if name in NAMES:
                calls[name]=calls.get(name,0)+1
        out["calls"]=calls
        out["status_references"]={n:n in source for n in STATES}
        out["has_main"]=any(isinstance(n,ast.If) and "__main__" in ast.dump(n.test) for n in tree.body)
        out["guard_references"]={n:n in source.lower() for n in (
            "private_chat","moderator_chat","shadow_only","dry_run",
            "public_channel","auto_delivery","photo_review")}
    except (SyntaxError,OSError,UnicodeError,ValueError):
        out["syntax"]="INVALID"
    return out

def shell_file(path,rel):
    out={"file":rel,"present":False}
    if not path.is_file() or path.is_symlink() or path.stat().st_size>800000:
        return out
    try:
        source=path.read_text(encoding="utf-8",errors="replace")
        out["present"]=True
        out["age_hours"]=max(0,round((time.time()-path.stat().st_mtime)/3600,1))
        out["called_script_basenames"]=sorted(set(SCRIPT_REF.findall(source)))[:35]
        out["photo_worker_directly_called"]="telegram_photo_review_flow.py" in source
        out["variable_commands_used"]="$(" in source or ("$"+"{") in source
    except OSError:
        pass
    return out

def database(root):
    db=next((p for p in (root/"news.sqlite3",root/"data/news.sqlite3",
                        root/"db/news.sqlite3",root/"state/news.sqlite3")
             if p.is_file() and not p.is_symlink()),None)
    if not db:
        return {"found":False}
    report={"found":True,"immutable_read_only":True,
            "wal_present":(db.parent/(db.name+"-wal")).exists(),"tables":[]}
    try:
        cx=sqlite3.connect(db.resolve().as_uri()+"?mode=ro&immutable=1",uri=True,timeout=2)
        start=time.monotonic()
        cx.set_progress_handler(lambda:1 if time.monotonic()-start>4 else 0,2500)
        try:
            cx.execute("PRAGMA query_only=ON")
            table_list=[r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            for name in table_list:
                if (not isinstance(name,str) or not re.fullmatch(r"[a-zA-Z0-9_]{1,60}",name)
                    or not any(w in name.lower() for w in ("photo","outbox","dispatch","moderation","queue"))):
                    continue
                quoted='"'+name+'"'
                columns={r[1] for r in cx.execute("PRAGMA table_info("+quoted+")")}
                entry={"name":name,"rows":cx.execute("SELECT COUNT(*) FROM "+quoted).fetchone()[0],
                       "status_counts":{}}
                for field in ("state","status","delivery_state","review_state"):
                    if field not in columns:continue
                    counts={}
                    for value,count in cx.execute("SELECT "+field+",COUNT(*) FROM "+quoted+
                                                  " GROUP BY "+field+" LIMIT 80"):
                        value=str(value).lower() if value is not None else "null"
                        val=value if value in SAFE_STATES else "other_redacted"
                        counts[val]=counts.get(val,0)+int(count)
                    entry["status_counts"][field]=counts
                report["tables"].append(entry)
        finally:
            cx.close()
    except (sqlite3.Error,OSError,ValueError):
        report["read_error"]=True
    return report

def inspect(root):
    files=[]
    for rel in FILES:
        p=root/rel
        files.append(shell_file(p,rel) if rel.endswith(".sh") else python_file(p,rel))
    return {"schema":"RG_NEWS2_PHOTO_REPAIR_PREFLIGHT_V1","read_only":True,
            "telegram_api_calls":0,"database_writes":0,"publications":0,
            "worker_invocations":0,"files":files,"database":database(root),
            "public_delivery_gate_preserved":True,
            "repair_not_applied":True}

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root=pathlib.Path(d)
        (root/"operator").mkdir()
        (root/"rg_news_dsm_tick.sh").write_text("#!/bin/sh\npython3 /x/outbound_tick.sh\n# TOKEN_PRIVATE\n")
        (root/"telegram_photo_review_flow.py").write_text("def deliver_one(db,send):\n  return 'pending'\n")
        (root/"operator/rg_news2_outbound_queue_v2.py").write_text(
            "from telegram_photo_review_flow import deliver_one\n"
            "def main(db,send):\n  return deliver_one(db,send)\n")
        cx=sqlite3.connect(str(root/"news.sqlite3"))
        cx.execute("CREATE TABLE photo_review_outbox(state TEXT,token TEXT)")
        cx.execute("INSERT INTO photo_review_outbox VALUES('pending','TOKEN_PRIVATE')")
        cx.commit();cx.close()
        result=inspect(root)
        assert result["files"][2]["definitions"]["deliver_one"]["args"]==2
        assert result["files"][1]["calls"]["deliver_one"]==1
        assert result["database"]["tables"][0]["status_counts"]["state"]["pending"]==1
        assert "TOKEN_PRIVATE" not in json.dumps(result)
    print("RG_NEWS2_PHOTO_REPAIR_PREFLIGHT_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["diagnose"]:
        print(json.dumps(inspect(ROOT),indent=2,sort_keys=True))
    else:raise SystemExit("Usage: selftest | diagnose")
