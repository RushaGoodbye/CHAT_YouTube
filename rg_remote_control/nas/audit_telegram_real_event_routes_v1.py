#!/usr/bin/env python3
"""Read-only forensic inventory of actual RG Telegram source routes and NAS export opportunities.
No secrets or user text, prints only line-numbered route/call-site signatures.
"""
import pathlib,re,json
ROOT=pathlib.Path("/volume1/docker/RG_ALERTS_DEPLOY/cloudflare-alerts/src")
FILES=("index.js","quota-entry.js","calendar-entry.js","telegram-moderation.js","moderation-ops.js")
PATTERN=re.compile(r"\b(fetch\(|scheduled\(|queue\(|getUpdates|sendPhoto|sendMessage|sendMediaGroup|poll\(|processTelegramModerationUpdates|runDoModerationWatchdog|airAlertCoordinatorRequest|MODERATION_COORDINATOR|ALERT_STATE|/health|/status|publish|moderation|alert)\b",re.I)
def main():
 out=[]
 for name in FILES:
  p=ROOT/name
  if not p.is_file() or p.is_symlink():continue
  lines=p.read_text("utf-8",errors="replace").splitlines()
  matches=[]
  for i,line in enumerate(lines,1):
   if PATTERN.search(line):
    # Report only presence of patterns, not source values, tokens or message text.
    tokens=sorted(set(m.group(0) for m in PATTERN.finditer(line)))
    matches.append({"line":i,"symbols":tokens})
  out.append({"file":name,"lines":len(lines),"matches":matches[:90],"truncated":len(matches)>90})
 print(json.dumps({"report":"RG_TELEGRAM_SOURCE_ROUTES_V1","read_only":True,"files":out},ensure_ascii=False))
if __name__=="__main__":main()
