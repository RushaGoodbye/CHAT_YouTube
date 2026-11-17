#!/usr/bin/env python3
"""NEWS RG one-news Gemini pilot using EXISTING credential if already present.

No new Telegram poller, getUpdates, moderator message, channel publication,
or edit of existing bot. Only isolated editorial shadow SQLite may be written.
Requires explicit pilot-one CLI and caps requests to one per invocation plus
the newsroom's atomic rolling-day quota. Never echoes secret values or news text.
"""
import importlib.util
import json
import os
import pathlib
import re
import sys
import tempfile

BASE=pathlib.Path("/volume1/docker")
NEWS=BASE/"RG_TELEGRAM_NEWS_2"
OP=NEWS/"operator"
R7=BASE/"RG_CONTENT_DEPLOY"
SOURCES=(R7/"deploy.env",R7/".env",NEWS/".env",OP/".env")
FILES=(BASE/"RG_SECRETS/gemini_api_key",BASE/"RG_SECRETS/google_api_key")
ALLOWED_MODEL=re.compile(r"^gemini-[a-zA-Z0-9_.-]{4,60}$")
ALLOWED_KEY=re.compile(r"^[A-Za-z0-9_-]{20,200}$")
ALLOWED_ENV={"GEMINI_API_KEY","GOOGLE_API_KEY","GOOGLE_GENAI_API_KEY"}
ALLOWED_MODELS={"GEMINI_MODEL","GOOGLE_MODEL","NEWS_RG_GEMINI_MODEL"}

def safe_file(path,max_bytes=70000):
    try:return path.is_file() and not path.is_symlink() and path.stat().st_size<=max_bytes
    except (OSError,ValueError):return False

def config(root=BASE):
    for base in SOURCES:
        p=root/base.relative_to(BASE)
        if not safe_file(p):continue
        try:lines=p.read_text("utf-8").splitlines()
        except (UnicodeError,OSError):continue
        values={}
        for line in lines:
            mat=re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*)$",line)
            if not mat:continue
            k,raw=mat.groups()
            if k not in ALLOWED_ENV|ALLOWED_MODELS:continue
            v=raw.strip().strip('"').strip("'")
            if v and "$" not in v and "\`" not in v:values[k]=v
        key=next((values[x] for x in ALLOWED_ENV if x in values
                  and ALLOWED_KEY.fullmatch(values[x])),None)
        if key:
            model=next((values[x] for x in ALLOWED_MODELS if
                        x in values and ALLOWED_MODEL.fullmatch(values[x])),None)
            return key,model,"existing_local_deploy_env"
    for item in FILES:
        p=root/item.relative_to(BASE)
        if not safe_file(p,8192):continue
        if p.stat().st_mode&0o077:continue
        try:value=p.read_text("utf-8").strip()
        except (UnicodeError,OSError):continue
        if ALLOWED_KEY.fullmatch(value):
            return value,None,"existing_protected_secret_file"
    return None,None,"no_existing_local_gemini_key"

def load_rewriter(op=OP):
    path=op/"news_rg_editorial_rewrite_shadow_v1.py"
    pol=op/"news_rg_editorial_contract_v1.py"
    if not safe_file(path,100000) or not safe_file(pol,100000):
        raise RuntimeError("INSTALLED_EDITORIAL_MODULES_MISSING")
    spec=importlib.util.spec_from_file_location("news_rg_editorial_installed",str(path))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def pilot(root=BASE,invoked=False):
    if not invoked:raise RuntimeError("EXPLICIT_PILOT_FLAG_REQUIRED")
    op=root/"RG_TELEGRAM_NEWS_2/operator"
    module=load_rewriter(op)
    secret,model,origin=config(root)
    if secret is None:
        return {"schema":"NEWS_RG_ONE_NEWS_EDITORIAL_PILOT_V1",
                "status":"EXISTING_LOCAL_GEMINI_CREDENTIAL_NOT_FOUND",
                "credential_origin":origin,"ai_requests":0,
                "telegram_calls":0,"new_pollers":0,"publications":0}
    existing=os.environ.get("GEMINI_API_KEY")
    try:
        os.environ["GEMINI_API_KEY"]=secret
        result=module.run(store=op/"news_rg_editorial_shadow_v1.sqlite3",
                          max_items=1,allowed=True,model=model)
        result["schema"]="NEWS_RG_ONE_NEWS_EDITORIAL_PILOT_V1"
        result["credential_origin"]=origin
        result["key_disclosed"]=False
        result["no_moderation_messages"]=True
        result["public_channel_enabled"]=False
        return result
    finally:
        if existing is None:os.environ.pop("GEMINI_API_KEY",None)
        else:os.environ["GEMINI_API_KEY"]=existing

def selftest():
    with tempfile.TemporaryDirectory() as t:
        root=pathlib.Path(t)
        deploy=root/"RG_CONTENT_DEPLOY";deploy.mkdir()
        (deploy/"deploy.env").write_text(
           "GEMINI_API_KEY=SECRET_GEMINI_TESTKEY_1234567890\n"
           "GEMINI_MODEL=gemini-3.5-flash-lite\n")
        key,model,origin=config(root)
        assert key=="SECRET_GEMINI_TESTKEY_1234567890"
        assert model=="gemini-3.5-flash-lite"
        assert origin=="existing_local_deploy_env"
        assert config(root/"nothing")[0] is None
        try:pilot(root,invoked=False)
        except RuntimeError:pass
        else:raise AssertionError("pilot flag missing")
        assert "SECRET_GEMINI_TESTKEY_1234567890" not in json.dumps({
                  "model_selected":model,"credential_origin":origin})
    print("NEWS_RG_ONE_NEWS_AI_PILOT_SELFTEST_PASS")

if __name__=="__main__":
    try:
        if sys.argv[1:]==["selftest"]:selftest()
        elif sys.argv[1:]==["pilot-one"]:
            print(json.dumps(pilot(invoked=True),sort_keys=True,
                             ensure_ascii=False,indent=2))
        elif sys.argv[1:]==["credential-status"]:
            key,model,origin=config()
            print(json.dumps({"schema":"NEWS_RG_EXISTING_LOCAL_AI_STATUS",
                "local_gemini_credential_available":bool(key),
                "model_configured":bool(model),
                "credential_origin":origin,"ai_requests":0,
                "telegram_calls":0},sort_keys=True,ensure_ascii=False,indent=2))
        else:raise RuntimeError("ONLY_SELFTEST_PILOT_ONE_CREDENTIAL_STATUS")
    except Exception as e:
        code=str(e)
        if not re.fullmatch(r"[A-Z_0-9]{4,80}",code):
            code="SAFE_STOP"
        print(json.dumps({"schema":"NEWS_RG_ONE_NEWS_EDITORIAL_PILOT_V1",
            "status":"SAFE_STOP","code":code,"ai_requests":"at_most_one",
            "telegram_calls":0,"publications":0}))
        sys.exit(2)
