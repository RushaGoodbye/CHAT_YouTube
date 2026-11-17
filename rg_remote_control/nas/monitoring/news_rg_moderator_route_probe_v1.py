#!/usr/bin/env python3
"""NEWS RG read-only callback & manual Telegram link routing interface proof.

Static AST inspection only; no imports of production modules, Telegram API,
network, process changes, secrets, chats, source code or SQL writes.
"""
import ast
import json
import pathlib
import re
import sys
import tempfile

ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
FILES={
    "native_callback":"operator/rg_news2_p31_guarded_callback_once.py",
    "legacy_bot":"rg_v18.py",
    "photo_worker":"telegram_photo_review_flow.py",
    "outbound_queue":"operator/rg_news2_outbound_queue_v2.py"
}
RELEVANT=("main","run","once","poll","update","callback","message",
          "handler","handle","moderation","telegram","accept","reject",
          "photo","text","link","receive")
KNOWN_METHODS={"getUpdates","get_updates","sendMessage","sendPhoto",
    "answerCallbackQuery","editMessageCaption","handle_callback"}
URL_RE=re.compile(r"t\.me/|telegram\.me/|tg://",re.I)
SENSITIVE=re.compile(r"token|secret|key|password|chat|id|recipient|api|"
                     r"credential|env|private",re.I)

def scan(root=ROOT):
    results={}
    for key,rel in FILES.items():
        p=root/rel
        if not p.is_file() or p.is_symlink() or p.stat().st_size>900000:
            results[key]={"regular_source_present":False}
            continue
        raw=p.read_text(encoding="utf-8",errors="replace")
        try:tree=ast.parse(raw)
        except SyntaxError:
            results[key]={"regular_source_present":True,"syntax_ok":False}
            continue
        defs=[n for n in ast.walk(tree) if isinstance(n,
                     (ast.FunctionDef,ast.AsyncFunctionDef))]
        brief=[n.name for n in defs if len(n.name)<80 and
               any(w in n.name.lower() for w in RELEVANT) and
               not SENSITIVE.search(n.name)]
        methods={name:0 for name in KNOWN_METHODS}
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call):continue
            label=(node.func.id if isinstance(node.func,ast.Name) else
                   node.func.attr if isinstance(node.func,ast.Attribute) else "")
            if label in methods:methods[label]+=1
        constants=[x.value for x in ast.walk(tree)
                   if isinstance(x,ast.Constant) and isinstance(x.value,str)]
        results[key]={
            "regular_source_present":True,"syntax_ok":True,
            "relevant_function_names":sorted(set(brief))[:35],
            "known_telegram_call_sites":{k:v for k,v in methods.items() if v},
            "contains_tme_ingest":any(URL_RE.search(x) for x in constants),
            "mentions_photo_review_flag":"photo_reviewed" in raw,
            "mentions_news_body_field":bool(re.search(r"\b(?:caption|body)\b",raw)),
            "mentions_gemini":"gemini" in raw.lower(),
            "mentions_manual_text_post":any(w in raw.lower()
                        for w in ("manual_link","text_post","import_link")),
        }
    tick=root/"rg_news_dsm_tick.sh"
    out={"schema":"NEWS_RG_MODERATOR_ROUTE_PROBE_V1",
         "read_only":True,"telegram_calls":0,"new_pollers_started":0,
         "processes_changed":0,"publications":0,"db_writes":0,
         "module_hints":results,
         "dsm_tick_present":tick.is_file() and not tick.is_symlink()}
    if out["dsm_tick_present"]:
        body=tick.read_text(encoding="utf-8",errors="replace")
        out["dsm_hook_private_photo"]= "RG_NEWS2_PRIVATE_FINAL_V1" in body
        out["dsm_tick_calls_native_callback"]= \
            "rg_news2_p31_guarded_callback_once.py" in body
        out["dsm_tick_calls_legacy_bot"]="rg_v18.py" in body
        out["dsm_tick_calls_shadow_ingest"]= \
            "news_rg_source_shadow_ingest_v1.py" in body
    return out

def selftest():
    with tempfile.TemporaryDirectory() as tmp:
        p=pathlib.Path(tmp)
        (p/"operator").mkdir()
        (p/"operator/rg_news2_p31_guarded_callback_once.py").write_text(
           "def handle_callback(x):\n  return getUpdates('SECRET_TOKEN_AND_CHAT')\n")
        (p/"rg_news_dsm_tick.sh").write_text("# RG_NEWS2_PRIVATE_FINAL_V1\n")
        r=scan(p)
        d=r["module_hints"]["native_callback"]
        assert d["known_telegram_call_sites"]["getUpdates"]==1,d
        assert not r["dsm_tick_calls_shadow_ingest"]
        assert "SECRET_TOKEN_AND_CHAT" not in json.dumps(r)
    print("NEWS_RG_MODERATOR_ROUTE_PROBE_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["inspect"]:
        print(json.dumps(scan(),ensure_ascii=False,sort_keys=True,indent=2))
    else:raise SystemExit("Only selftest or inspect supported")
