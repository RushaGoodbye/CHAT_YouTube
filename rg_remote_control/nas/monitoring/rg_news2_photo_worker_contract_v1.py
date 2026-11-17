#!/usr/bin/env python3
"""Static, read-only NEWS2 photo-worker entrypoint inventory. No execution."""
import ast
import json
import pathlib
import hashlib

ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
SOURCES=(
    "telegram_photo_review_flow.py",
    "operator/telegram_native_candidate_20261025/telegram_photo_review_flow.py",
    "operator/telegram_native_candidate_20261025_v2/telegram_photo_review_flow.py",
    "operator/telegram_native_candidate_20261025_v3/telegram_photo_review_flow.py",
)
CALLS=("sqlite3","connect","execute","executemany","commit","getUpdates",
       "get_updates","sendPhoto","sendMessage","requests","urlopen",
       "argparse","ArgumentParser","parse_args","create_task")
TOKENS=("awaiting_photo_review","photo_reviewed","awaiting_moderation",
        "photo_review_note","photo_url","image_url","moderation_dispatch")
def inspect(root):
    result=[]
    for rel in SOURCES:
        p=root/rel
        row={"variant":rel.split("/")[1] if "/" in rel else "root","exists":p.is_file()}
        if not p.is_file() or p.is_symlink() or p.stat().st_size>500000:
            result.append(row)
            continue
        try:
            code=p.read_text(encoding="utf-8")
            tree=ast.parse(code)
            row["sha256_prefix"]=hashlib.sha256(code.encode()).hexdigest()[:12]
            row["bytes"]=p.stat().st_size
            row["top_level_functions"]=[n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))][:35]
            row["classes"]=[n.name for n in tree.body if isinstance(n,ast.ClassDef)][:12]
            row["imports"]=sorted({a.name.split(".")[0] for n in tree.body if isinstance(n,ast.Import) for a in n.names})[:35]
            row["call_presence"]={s:any(isinstance(n,ast.Call) and
                (isinstance(n.func,ast.Name) and n.func.id==s or
                 isinstance(n.func,ast.Attribute) and n.func.attr==s)
                for n in ast.walk(tree)) for s in CALLS}
            row["db_state_references"]={k:k in code for k in TOKENS}
            row["has_main_entry"]=any(isinstance(n,ast.If) and
                isinstance(n.test,ast.Compare) and ast.dump(n.test).find("__main__")>=0
                for n in tree.body)
            row["syntax"]="PASS"
        except (OSError,ValueError,SyntaxError):
            row["syntax"]="ERROR"
        result.append(row)
    return {"schema":"RG_NEWS2_PHOTO_WORKER_CONTRACT_V1","read_only":True,
            "scripts_executed":0,"telegram_api_calls":0,"files":result}
def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p=pathlib.Path(d)/SOURCES[0]
        p.write_text("import sqlite3\ndef review(x):\n  return 'photo_reviewed'\n")
        r=inspect(pathlib.Path(d))
        assert r["files"][0]["syntax"]=="PASS"
        assert r["files"][0]["top_level_functions"]==["review"]
        assert r["scripts_executed"]==0
    print("RG_NEWS2_PHOTO_WORKER_CONTRACT_SELFTEST_PASS")
if __name__=="__main__":
    import sys
    if sys.argv[1:] == ["selftest"]:
        selftest()
    elif sys.argv[1:] == ["diagnose"]:
        print(json.dumps(inspect(ROOT),sort_keys=True,indent=2))
    else:
        raise SystemExit("Usage: selftest | diagnose")
