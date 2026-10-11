#!/usr/bin/env python3
"""Read-only bounded inspection of actual Telegram deployment source synchronization."""
import json, pathlib, re, sys
FILE=pathlib.Path("/volume1/docker/RG_NAS_AUTO_DEPLOY.sh")
RANGES=[(405,465),(465,620),(620,780),(780,930),(930,1080),(1080,1220),(1220,1302)]
KEEP=re.compile(r"(?i)alert|video|content|sync|copy|tar|unzip|fetch|source|wrangler|deploy|checkout|worker|sha|branch|cloudflare|npm|docker|cp\s|mv\s|rm\s|curl\s|git\s|quota|guard|python|\.js")
DANGER=re.compile(r"(?i)(api.?token|password|secret|authorization|bearer|private.?key|credential|GITHUB_TOKEN|CF_TOKEN|CLOUDFLARE_API_TOKEN)")
def run():
    if not FILE.is_file() or FILE.is_symlink() or FILE.stat().st_size>400000:
        raise SystemExit("BLOCKED: auto deploy file unavailable")
    lines=FILE.read_text("utf-8",errors="replace").splitlines()
    output={"report":"RG_TELEGRAM_DEPLOY_SYNC_PATH_V1","read_only":True,"file":str(FILE),"total_lines":len(lines),"ranges":[]}
    for start,end in RANGES:
        matches=[]
        for lineno in range(start,min(end,len(lines))+1):
            line=lines[lineno-1]
            if KEEP.search(line):
                matches.append({"line":lineno,"text":"[REDACTED]" if DANGER.search(line) else line.strip()[:160]})
        output["ranges"].append({"range":f"{start}-{end}","matches":matches[:90],"truncated":len(matches)>90})
    print(json.dumps(output,ensure_ascii=False,indent=2))
if __name__=="__main__":
    run()
