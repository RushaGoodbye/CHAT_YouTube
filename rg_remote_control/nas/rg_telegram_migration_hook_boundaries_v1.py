#!/usr/bin/env python3
"""Inspect external dependency shapes for NAS migration; never print credentials, URLs or secrets."""
import json,pathlib,re
root=pathlib.Path("/volume1/docker/RG_ALERTS_DEPLOY/cloudflare-alerts/src")
ranges={"index.js":[(1078,1122),(1544,1574)],"telegram-moderation.js":[(115,150),(2665,2705)],"calendar-entry.js":[(48,71)]}
filters={
"alert_sources":["fetch(","env.","get(","poll(","parse","json(","response","status","provider","district"],
"moderation":["getUpdates","sendMessage","sendPhoto","update_id","callback_query","offset","await"],
"schedule":["scheduled","poll(","processTelegramModerationUpdates","minuteSilence","waitUntil"]
}
out=[]
for name,groups in ranges.items():
 p=root/name
 if not p.is_file():continue
 ls=p.read_text(encoding="utf8",errors="replace").splitlines()
 chunks=[]
 for a,b in groups:
  rows=[]
  for number in range(a,min(b,len(ls))+1):
   line=ls[number-1]
   # classify without emitting code values
   operations=[token for token in set(sum(filters.values(),[])) if token.lower() in line.lower()]
   if operations:
    rows.append({"line":number,"operations":sorted(operations)})
  chunks.append({"range":[a,b],"operations":rows})
 out.append({"file":name,"chunks":chunks})
print(json.dumps({"schema":"RG_TELEGRAM_MIGRATION_HOOK_BOUNDARIES_V1","read_only":True,"source_content_disclosed":False,"files":out}))
