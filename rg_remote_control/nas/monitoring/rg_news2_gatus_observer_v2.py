#!/usr/bin/env python3
"""Gatus observer for the ACTIVE NEWS2 callback (liveness only, no Telegram API).

Read-only scans under /nas/RG_TELEGRAM_NEWS_2, never reads chat text, tokens,
photo cards, database content, or private messages. Only explicit --push sends
health flags to the isolated, local Gatus container.
"""
from __future__ import annotations
import argparse
import json
import os
import pathlib
import stat
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CHECKS = {
    "news2-callback-state": ("callback_v29_state.json", "rg-nas_news2-callback-state"),
    "news2-callback-log": ("callback_v29.log", "rg-nas_news2-callback-log"),
}
MAX_AGE = 300

def locate(root: pathlib.Path, name: str):
    found=[]
    if not root.is_dir() or root.is_symlink():
        return found
    for parent, dirs, files in os.walk(root, followlinks=False):
        depth=len(pathlib.Path(parent).relative_to(root).parts)
        dirs[:] = [d for d in dirs if depth < 4 and not d.startswith(".")
                   and not (pathlib.Path(parent)/d).is_symlink()
                   and d.lower() not in ("backup","backups","cache","secrets","venv")]
        if name in files:
            file=pathlib.Path(parent)/name
            try:
                if file.is_file() and not file.is_symlink() and file.stat().st_size <= 2*1024*1024:
                    found.append(file)
            except OSError:
                pass
    return found

def observe(root: pathlib.Path, now: datetime | None=None) -> dict:
    now=now or datetime.now(timezone.utc)
    results={}
    folder=root/"RG_TELEGRAM_NEWS_2"
    for key,(filename,_) in CHECKS.items():
        files=locate(folder,filename)
        if not files:
            results[key]={"success":False,"reason":"missing file"}
            continue
        good=[]
        for file in files:
            try:
                age=(now.timestamp()-file.stat().st_mtime)
                fresh=-120<=age<=MAX_AGE
                if fresh and filename.endswith(".json"):
                    with file.open(encoding="utf-8") as stream:
                        payload=json.load(stream)
                    fresh = isinstance(payload,dict)
                if fresh:
                    good.append(file)
            except (OSError,ValueError,TypeError,UnicodeError,json.JSONDecodeError):
                pass
        results[key]={"success":bool(good),
                      "reason":"fresh runtime file" if good else "stale or invalid runtime file"}
    return results

def token(path: pathlib.Path) -> str:
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("insecure private token file permissions")
    value=path.read_text(encoding="utf-8").strip()
    if len(value)<32 or any(c.isspace() for c in value):
        raise ValueError("invalid local token")
    return value

def push(results: dict, local_url: str, secret: str) -> None:
    if local_url not in ("http://gatus:8080","http://127.0.0.1:18080","http://localhost:18080"):
        raise ValueError("external destinations prohibited")
    for key,value in results.items():
        args={"success":str(value["success"]).lower()}
        if not value["success"]:
            args["error"]=value["reason"]
        address=local_url+"/api/v1/endpoints/"+CHECKS[key][1]+"/external?"+urlencode(args)
        request=Request(address,data=b"",method="POST",headers={"Authorization":"Bearer "+secret})
        with urlopen(request,timeout=5) as resp:
            if not 200<=resp.status<300:
                raise RuntimeError("Gatus HTTP "+str(resp.status))

def main(argv=None) -> int:
    cli=argparse.ArgumentParser()
    cli.add_argument("--root",type=pathlib.Path,default=pathlib.Path("/nas"))
    cli.add_argument("--url",default="http://gatus:8080")
    cli.add_argument("--token-file",type=pathlib.Path,default=pathlib.Path("/run/monitor-token"))
    cli.add_argument("--push",action="store_true")
    args=cli.parse_args(argv)
    status=observe(args.root)
    if args.push:
        push(status,args.url,token(args.token_file))
    print(json.dumps({"schema":"RG_NEWS2_OBSERVER_V2","liveness_only":True,
                      "public_channel_delivery_not_checked":True,
                      "checks":status,"pushed":args.push},
                     sort_keys=True,ensure_ascii=False))
    return 0 if all(item["success"] for item in status.values()) else 2

def selftest():
    import tempfile
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as name:
        root=pathlib.Path(name)
        state=root/"RG_TELEGRAM_NEWS_2"/"run"
        state.mkdir(parents=True)
        now=datetime.now(timezone.utc)
        assert not any(x["success"] for x in observe(root,now).values())
        (state/"callback_v29_state.json").write_text('{"ok":true}',encoding="utf-8")
        (state/"callback_v29.log").write_text("ok\n",encoding="utf-8")
        assert all(x["success"] for x in observe(root,now).values())
        (state/"callback_v29_state.json").write_text("{",encoding="utf-8")
        assert observe(root,now)["news2-callback-state"]["success"] is False
        with patch(__name__+".urlopen",side_effect=AssertionError("network forbidden")):
            assert main(["--root",str(root)])==2
        try:
            push(observe(root,now),"https://example.com","fake")
        except ValueError:
            pass
        else:
            raise AssertionError("remote destination accepted")
        assert not (root/"RG_NAS_STATE").exists()
    print("RG_NEWS2_OBSERVER_V2_SELFTEST_PASS")

if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="selftest":
        selftest()
    else:
        sys.exit(main())
