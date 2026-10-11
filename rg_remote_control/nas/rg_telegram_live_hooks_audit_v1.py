#!/usr/bin/env python3
"""Read-only Telegram migration integration audit: safe structural slices, no strings or secrets."""
import ast, json, pathlib, re
root=pathlib.Path("/volume1/docker/RG_ALERTS_DEPLOY/cloudflare-alerts/src")
locations={"index.js":[(1060,1120),(1538,1599)],"telegram-moderation.js":[(105,165),(1080,1130),(2630,2690)],"calendar-entry.js":[(43,75)]}
pattern=re.compile(r"(?i)(async|function|export|await|return|if\s*\(|scheduled|poll\(|sendPhoto|sendMessage|getUpdates|processTelegramModerationUpdates|maybePublishMinuteSilence|fetch\(|env\.|\.put\(|\.get\(|\.delete\()")
bad=re.compile(r"(?i)(token|secret|key|password|authorization|bearer|private|https?://|telegram\.org)")
for file,ranges in locations.items():
 p=root/file
 if not p.is_file():print(json.dumps({"file":file,"error":"missing"}));continue
 source=p.read_text("utf-8",errors="replace").splitlines()
 chunks=[]
 for start,end in ranges:
  lines=[]
  for i in range(start,min(end,len(source))+1):
   line=source[i-1]
   if not pattern.search(line):continue
   # Do not expose expressions or string literals. Retain only categorized operations and line numbers.
   kinds=[]
   for symbol in ("poll(","sendPhoto","sendMessage","getUpdates","scheduled","processTelegramModerationUpdates","maybePublishMinuteSilence","fetch(",".put(",".get(","return","await","function","async"):
    if symbol.lower() in line.lower():kinds.append(symbol)
   if kinds: lines.append({"line":i,"operations":kinds})
  chunks.append({"start":start,"end":end,"operations":lines})
 print(json.dumps({"file":file,"chunks":chunks},ensure_ascii=False))
