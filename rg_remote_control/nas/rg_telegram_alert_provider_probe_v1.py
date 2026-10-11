#!/usr/bin/env python3
"""Read-only source audit for alert provider path. Outputs tokens/identifier names only."""
import pathlib,re,json
p=pathlib.Path("/volume1/docker/RG_ALERTS_DEPLOY/cloudflare-alerts/src/index.js")
if not p.is_file():raise SystemExit("SOURCE_MISSING")
src=p.read_text("utf-8",errors="replace").splitlines()
ranges=[(1,115),(1030,1170),(1510,1575)]
terms=re.compile(r"provider|ubilling|alert|api|fetch|poll|status|region|kyiv",re.I)
out=[]
for lo,hi in ranges:
 hits=[]
 for i in range(lo,min(hi,len(src))+1):
  line=src[i-1]
  if not terms.search(line):continue
  ops=sorted({x for x in ["provider","ubilling","fetch(","poll(","ALERT_STATE","await","kyiv","status","JSON.parse","response.json","env."] if x.lower() in line.lower()})
  if ops:hits.append({"line":i,"signals":ops})
 out.append({"range":[lo,hi],"hits":hits})
print(json.dumps({"status":"READ_ONLY","source":"index.js","sections":out,"network_calls":0},ensure_ascii=False))
