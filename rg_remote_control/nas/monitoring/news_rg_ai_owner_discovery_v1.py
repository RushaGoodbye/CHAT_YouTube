#!/usr/bin/env python3
"""NEWS RG: find EXISTING content hub and permitted AI config without secrets.

Read-only. Never prints values/URLs/tokens/paths containing credentials, never
makes network requests or imports runtime code. Supports Synology Python 3.8.
"""
import ast
import collections
import json
import os
import pathlib
import re
import sqlite3
import sys
import tempfile

ROOT = pathlib.Path("/volume1/docker")
NEWS = ROOT/"RG_TELEGRAM_NEWS_2"
R7 = ROOT/"RG_CONTENT_DEPLOY"
CONF_FILES = (
    ROOT/"RG_CONTENT_DEPLOY/deploy.env",
    ROOT/"RG_CONTENT_DEPLOY/.env",
    ROOT/"RG_ALERTS_DEPLOY/deploy.env",
    ROOT/"RG_DEPLOY/deploy.env",
    ROOT/"RG_TELEGRAM_NEWS_2/.env",
    ROOT/"RG_TELEGRAM_NEWS_2/operator/.env",
)
SECRET_FILES = (
    ("gemini", ROOT/"RG_SECRETS/gemini_api_key"),
    ("google", ROOT/"RG_SECRETS/google_api_key"),
    ("openai", ROOT/"RG_SECRETS/openai_api_key"),
)
RECOGNIZED = {
    "GEMINI_API_KEY":"gemini",
    "GOOGLE_API_KEY":"gemini",
    "OPENAI_API_KEY":"openai",
    "GOOGLE_GENAI_API_KEY":"gemini",
    "AI_PROVIDER":"provider_choice",
    "AI_MODEL":"model_choice",
    "GEMINI_MODEL":"model_choice",
    "NEWS_RG_GEMINI_MODEL":"model_choice",
    "CF_API_TOKEN":"cloudflare_control",
    "CLOUDFLARE_API_TOKEN":"cloudflare_control",
    "CLOUDFLARE_ACCOUNT_ID":"cloudflare_control",
    "CF_ACCOUNT_ID":"cloudflare_control",
    "CLOUDFLARE_ACCOUNT":"cloudflare_control",
    "AI_ENABLED":"ai_runtime_switch",
    "CONTENT_HUB_ENABLED":"content_hub_switch",
}
CODE_IDENTIFIERS = {
    "gemini_api_url":("generativelanguage.googleapis.com","generativelanguage.google.com"),
    "openai_api_url":("api.openai.com",),
    "ai_provider_ref":("gemini","openai","anthropic","google-generativeai"),
    "cloudflare_worker_ref":("rasha-goodbye-content-hub",),
    "content_worker_ref":("content_hub","content-hub"),
    "image_processing_ref":("sendphoto","photo_url","image_url"),
    "telegram_ingest_ref":("t.me/s/","telegram_link"),
}
VALUE_RE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]+)\s*=\s*(.*)$")

def safe_regular(path, limit=200000):
    try:
        return path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= limit
    except (OSError, ValueError):
        return False

def env_tags(path):
    if not safe_regular(path):return {"available":False}
    tags=collections.Counter()
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                match=VALUE_RE.match(line)
                if not match:continue
                key, raw = match.groups()
                if key in RECOGNIZED and raw.strip() and raw.strip() not in ("''",'""'):
                    tags[RECOGNIZED[key]]+=1
    except (OSError,UnicodeError):
        return {"available":True, "inspect_ok":False}
    return {"available":True,"inspect_ok":True,
            "recognized_present_groups":sorted(tags)}

def code_markers(root):
    groups=collections.Counter()
    walked=0
    if not root.is_dir() or root.is_symlink():
        return {"available":False}
    # Configuration and secrets never enter this code-read inventory.
    for item in root.glob("*"):
        candidates=([item] if item.is_file() else
             list(item.glob("*"))[:80] if item.is_dir() and not item.is_symlink() else [])
        for p in candidates:
            if walked>=100:break
            if p.suffix.lower() not in (".py",".js",".ts",".sh",".mjs"):
                continue
            if not safe_regular(p,100000):continue
            walked+=1
            try:
                body=p.read_text(encoding="utf-8",errors="replace").lower()
            except (OSError,ValueError):continue
            for label,needles in CODE_IDENTIFIERS.items():
                if any(needle in body for needle in needles):
                    groups[label]+=1
        if walked>=100:break
    return {"available":True,"source_files_inspected":walked,
            "abstract_code_features":dict(sorted(groups.items()))}

def shadow_state(root):
    path=root/"RG_TELEGRAM_NEWS_2/operator/news_rg_editorial_shadow_v1.sqlite3"
    if not safe_regular(path,50000000):
        return {"available":False}
    cx=sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)
    cx.execute("PRAGMA query_only=ON")
    try:
        tab={r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"story_shadow","editorial_draft"}.issubset(tab):
            return {"available":True,"expected_tables_present":False}
        states=dict(cx.execute("SELECT status,COUNT(*) FROM story_shadow GROUP BY status"))
        return {"available":True, "expected_tables_present":True,
          "pending_rewrite":states.get("needs_editorial_rewrite",0),
          "editorial_ready":states.get("editorial_ready",0),
          "manual_link_queued":cx.execute("SELECT COUNT(*) FROM story_shadow "
                           "WHERE origin='manual_link'").fetchone()[0]}
    finally:cx.close()

def audit(root=ROOT):
    checked={}
    for p in CONF_FILES:
        try:rel=str(p.relative_to(ROOT))
        except ValueError:continue
        checked[rel]=env_tags(root/rel)
    secret_files={}
    for tag,p in SECRET_FILES:
        rel=p.relative_to(ROOT)
        x=root/rel
        secret_files[tag]={"secure_regular_file_present":safe_regular(x,8192) and
                            x.stat().st_mode & 0o077==0}
    discovered=any(("gemini" in v.get("recognized_present_groups",[]) for v in checked.values()))
    discovered=discovered or any(secret_files[x]["secure_regular_file_present"]
                                 for x in ("gemini","google"))
    return {
       "schema":"NEWS_RG_EXISTING_AI_OWNER_DISCOVERY_V1",
       "read_only":True,"network_calls":0,"telegram_calls":0,
       "publications":0,"pollers_started":0,"sqlite_writes":0,
       "credential_values_exposed":False,
       "historical_content_hub":code_markers(root/"RG_CONTENT_DEPLOY"),
       "checked_config_locations":checked,
       "fixed_whitelist_secret_file_presence":secret_files,
       "gemini_provider_credential_file_or_env_candidate_present":discovered,
       "provider_authorization_verified":False,
       "model_quota_verified":False,
       "shadow":shadow_state(root),
       "next":"Use only a verified existing provider, never post or start second poller."
    }

def selftest():
    with tempfile.TemporaryDirectory() as t:
        root=pathlib.Path(t)
        dest=root/"RG_CONTENT_DEPLOY";dest.mkdir()
        (dest/"deploy.env").write_text("GEMINI_API_KEY=SECRET_TOKEN_123\nOPENAI_API_KEY=OTHER_SECRET\nCLOUDFLARE_ACCOUNT_ID=ACCOUNT_SECRET\n",encoding="utf-8")
        (dest/"worker.py").write_text("AI_HOST = 'https://generativelanguage.googleapis.com/v1'\n")
        news=root/"RG_TELEGRAM_NEWS_2/operator";news.mkdir(parents=True)
        cx=sqlite3.connect(str(news/"news_rg_editorial_shadow_v1.sqlite3"))
        cx.execute("CREATE TABLE story_shadow (status TEXT,origin TEXT)")
        cx.execute("CREATE TABLE editorial_draft (key TEXT)")
        cx.execute("INSERT INTO story_shadow VALUES('needs_editorial_rewrite','approved_source')")
        cx.commit();cx.close()
        out=audit(root)
        rendered=json.dumps(out)
        assert out["gemini_provider_credential_file_or_env_candidate_present"]
        assert out["shadow"]["pending_rewrite"]==1
        assert out["network_calls"]==0
        assert "SECRET_TOKEN_123" not in rendered and "OTHER_SECRET" not in rendered
        assert "ACCOUNT_SECRET" not in rendered
    print("NEWS_RG_EXISTING_AI_OWNER_DISCOVERY_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["inspect"]:
        print(json.dumps(audit(),sort_keys=True,ensure_ascii=False,indent=2))
    else:raise SystemExit("Only selftest or inspect supported")
