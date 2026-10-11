#!/usr/bin/env python3
"""Read-only deploy pipeline inspection. Redacts secrets and reports candidate sync/deploy steps."""
import json, pathlib, re
ROOT=pathlib.Path("/volume1/docker")
FILES=[ROOT/"RG_NAS_AUTO_DEPLOY.sh",ROOT/"RG_NAS_SCHEDULER_TICK.sh",ROOT/"RG_ALERTS_DEPLOY"/"deploy.sh"]
TERMS=re.compile(r"wrangler|cloudflare|quota|git |git$|rsync|cp |curl |deploy|npm |pnpm|node |quota-entry|telegram|alerts",re.I)
SECRET=re.compile(r"token|secret|password|authorization|api.key|credential|private.key|bearer|access.key",re.I)
def inspect(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size>1500000:
        return {"file":str(path),"status":"missing_or_unreadable"}
    rows=path.read_text("utf-8",errors="replace").splitlines()
    hits=[]
    for i,line in enumerate(rows,1):
        if TERMS.search(line):
            if SECRET.search(line): shown="[REDACTED]"
            else: shown=line.strip()[:180]
            hits.append({"line":i,"text":shown})
    return {"file":str(path),"total_lines":len(rows),"matches":hits[:110],"truncated":len(hits)>110}
def main():
    print(json.dumps({"report":"RG_TELEGRAM_DEPLOY_PIPELINE_AUDIT_V1","read_only":True,"files":[inspect(p) for p in FILES]},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
