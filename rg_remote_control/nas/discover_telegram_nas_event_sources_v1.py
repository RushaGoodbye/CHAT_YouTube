#!/usr/bin/env python3
"""Read-only, secret-safe discovery of Telegram event sources on NAS.
Print file names/types/sizes/mtime only. Never read candidate file contents.
"""
import json, pathlib, time, os
ROOTS=[pathlib.Path("/volume1/docker/RG_NAS_STATE"),pathlib.Path("/volume1/docker/RG_ALERTS_DEPLOY"),pathlib.Path("/volume1/docker/RG_CONTENT_DEPLOY"),pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE")]
KEYWORDS=("alert","publish","moder","queue","scanner","content","silence","inbox","event","journal","telegram","sent")
EXCLUDE=("node_modules",".git",".wrangler","dist","backup","cache","venv","tmp")
def sample(root):
    results=[]
    if not root.is_dir():return results
    for base,dirs,files in os.walk(root):
        rel=pathlib.Path(base).relative_to(root)
        if len(rel.parts)>=4:dirs[:]=[];continue
        dirs[:]=[d for d in dirs if not d.startswith(".") and not any(x in d.lower() for x in EXCLUDE)][:35]
        for name in files:
            p=pathlib.Path(base)/name
            low=name.lower()
            if not any(x in low for x in KEYWORDS):continue
            if any(x in low for x in ("secret","token","env","key","credential","password","auth")):continue
            if p.is_symlink():continue
            try: st=p.stat()
            except OSError:continue
            if not p.is_file():continue
            results.append({"relative_path":str(p.relative_to(root)),"bytes":st.st_size,"modified_age_sec":max(0,int(time.time()-st.st_mtime))})
            if len(results)>=100:return results
    return results
print(json.dumps({"report":"RG_TELEGRAM_EVENT_SOURCE_DISCOVERY_V1","read_only":True,"contents_read":False,"roots":[{"root":str(x),"candidates":sample(x)} for x in ROOTS]},ensure_ascii=False))
