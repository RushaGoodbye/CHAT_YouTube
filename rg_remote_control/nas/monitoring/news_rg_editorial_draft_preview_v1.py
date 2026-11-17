#!/usr/bin/env python3
"""NEWS RG one-draft local quality preview from shadow, NOT a Telegram send."""
import html
import importlib.util
import json
import pathlib
import re
import sqlite3
import sys
import tempfile

HERE=pathlib.Path(__file__).resolve().parent
SHADOW=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2/operator/news_rg_editorial_shadow_v1.sqlite3")
def policy():
    path=HERE/"news_rg_editorial_contract_v1.py"
    if not path.is_file() or path.is_symlink():raise RuntimeError("POLICY_FILE_MISSING")
    spec=importlib.util.spec_from_file_location("news_rg_contract_preview",str(path))
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def inspect(path=SHADOW,include_body=False):
    if not path.is_file() or path.is_symlink():raise RuntimeError("SHADOW_DB_MISSING")
    cx=sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)
    cx.execute("PRAGMA query_only=ON")
    try:
        data=cx.execute("""SELECT d.headline,d.body,s.media_url,
                    s.media_type,s.origin FROM editorial_draft d
                    JOIN story_shadow s ON d.key=s.key
                    WHERE s.status='editorial_ready'
                    ORDER BY d.validated_at DESC LIMIT 1""").fetchone()
        if not data:
            return {"schema":"NEWS_RG_EDITORIAL_DRAFT_PREVIEW_V1",
                    "status":"NO_READY_NEWS_DRAFT",
                    "telegram_calls":0,"publications":0}
        headline,body,media_url,media_type,origin=data
        report=policy().validate_editorial(headline,body,media_url)
        output={"schema":"NEWS_RG_EDITORIAL_DRAFT_PREVIEW_V1",
                "status":"READY_FOR_PRIVATE_PREVIEW" if
                         report["editorial_format_ready"] else "DRAFT_NOT_READY",
                "checks":report,"real_source_media_type":media_type,
                "media_url_present":bool(media_url),
                "media_file_verified":False,
                "external_links_in_preview":False,
                "origin_type":origin,
                "telegram_calls":0,"publications":0}
        if include_body and report["editorial_format_ready"]:
            # Local operator preview, NEVER printed to automation logs by default.
            output["headline"]=headline
            output["ukrainian_news_post"]=body
        return output
    finally:cx.close()

def selftest():
    with tempfile.TemporaryDirectory() as t:
        p=pathlib.Path(t)/"temp.sqlite3"
        cx=sqlite3.connect(str(p))
        cx.execute("CREATE TABLE story_shadow(key TEXT,status TEXT,media_url TEXT,media_type TEXT,origin TEXT)")
        cx.execute("CREATE TABLE editorial_draft(key TEXT,headline TEXT,body TEXT,validated_at INT)")
        cx.commit();cx.close()
        assert inspect(p)["status"]=="NO_READY_NEWS_DRAFT"
    print("NEWS_RG_EDITORIAL_DRAFT_PREVIEW_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["inspect"]:
        print(json.dumps(inspect(),sort_keys=True,ensure_ascii=False,indent=2))
    elif sys.argv[1:]==["operator-preview"]:
        print(json.dumps(inspect(include_body=True),ensure_ascii=False,indent=2))
    else:raise SystemExit("Only selftest, inspect or operator-preview supported")
