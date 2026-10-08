#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only 886 checkpoint and resume diagnosis. Never starts production."""
from __future__ import annotations
import datetime
import json
import os
import pathlib
import re
import time
import xml.etree.ElementTree as ET

APP=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=pathlib.Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
EGOR=pathlib.Path(r"D:\YOUTUBE\RUSHA GOODBYE\Раша GOODBYЕ\ГОТОВО\YouTube\ЕГОР")
PRIMARY=re.compile(r"^RG_EDITED_886_(\d+)\.xml$",re.I)
ANY_XML=re.compile(r"^RG_EDITED_886(?:_\d+)?(?:_[A-Za-z0-9]+)*\.xml$",re.I)
START=time.monotonic()

def iso(st):
    return datetime.datetime.fromtimestamp(st,datetime.timezone.utc).isoformat()
def summarize_xml(p):
    item={"path":str(p),"bytes":p.stat().st_size,"last_modified_utc":iso(p.stat().st_mtime)}
    match=PRIMARY.match(p.name)
    if match:item["dialogue"]=int(match.group(1))
    try:
        root=ET.parse(p).getroot()
        clips=root.findall(".//clipitem")
        item["premiere_xml_valid"]=(root.tag=="xmeml" and root.find("sequence") is not None and bool(clips))
        item["clipitems"]=len(clips)
    except Exception as exc:
        item["premiere_xml_valid"]=False
        item["xml_error"]=repr(exc)[:220]
    return item

def scan_tree(root, *, max_files=100000, time_budget=12.0):
    result={"root":str(root),"exists":root.is_dir(),"matches":[],"files_examined":0,"complete":False}
    if not root.is_dir():return result
    began=time.monotonic()
    dirs=[root]
    while dirs and result["files_examined"]<max_files and time.monotonic()-began<time_budget:
        folder=dirs.pop()
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    if time.monotonic()-began>=time_budget:break
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name not in ("__pycache__", ".git", "node_modules", "site-packages"):
                                dirs.append(pathlib.Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            result["files_examined"]+=1
                            if ANY_XML.fullmatch(entry.name):
                                p=pathlib.Path(entry.path)
                                result["matches"].append(summarize_xml(p))
                    except (PermissionError,OSError,ValueError):
                        continue
        except (PermissionError,OSError):
            continue
    result["complete"]=not dirs and time.monotonic()-began<time_budget
    result["matches"].sort(key=lambda r:(r.get("dialogue",1000),r["path"].lower()))
    result["matches"]=result["matches"][:90]
    return result

def code_evidence():
    p=APP/"rg_multi_dialogue.py"
    out={"path":str(p),"exists":p.is_file()}
    if not p.is_file():return out
    lines=p.read_text(encoding="utf-8-sig",errors="replace").splitlines()
    terms=("prior_xml", "can_resume", "RG_RESUME_PROTECT_PREFIX", "output_dir", "dialogue_output")
    indices=[i for i,line in enumerate(lines) if any(t in line for t in terms)]
    windows=[]
    for i in indices[:22]:
        a=max(0,i-8)
        b=min(len(lines),i+12)
        windows.append({"hit_line":i+1,"excerpt":"\n".join(f"{j+1}: {lines[j]}" for j in range(a,b))})
    out["resume_evidence"]=windows
    out["source_lines"]=len(lines)
    return out

def run_state():
    m=APP/"run_manifests"/"886"
    out={"path":str(m),"exists":m.is_dir(),"recent":[]}
    if m.is_dir():
        files=sorted((p for p in m.iterdir() if p.is_file()),key=lambda p:p.stat().st_mtime,reverse=True)
        for p in files[:15]:
            rec={"name":p.name,"size":p.stat().st_size,"modified_utc":iso(p.stat().st_mtime)}
            if p.suffix.lower() in (".log",".txt"):
                try:
                    lines=p.read_text(encoding="utf-8-sig",errors="replace").splitlines()
                    rec["tail"]=lines[-15:]
                except OSError:pass
            out["recent"].append(rec)
    return out

def main():
    search_roots=[
        APP,
        DATA/"release_backups",
        DATA/"validation",
        EGOR,
    ]
    # Root APP contains the active stream and .rg_revisions, and is searched only once.
    roots=[scan_tree(root,time_budget=12.0,max_files=140000) for root in search_roots]
    catalog={}
    for root in roots:
        for match in root["matches"]:
            n=match.get("dialogue")
            if n is not None and n<=10:
                catalog.setdefault(str(n),[]).append(match)
    print("=== RG 886 CHECKPOINT ROOT CAUSE V1 ===",flush=True)
    print(json.dumps({
        "schema":"RG_886_CHECKPOINT_ROOT_CAUSE_V1",
        "read_only":True,
        "production_started":False,
        "search_scopes":roots,
        "primary_dialogues_found":sorted(catalog.keys(),key=int),
        "missing_primary_dialogues_in_scanned_roots":[i for i in range(1,5) if str(i) not in catalog],
        "multi_dialogue_resume_code":code_evidence(),
        "run_manifest":run_state(),
        "elapsed_sec":round(time.monotonic()-START,2),
    },ensure_ascii=False,indent=2),flush=True)

if __name__=="__main__":
    main()
