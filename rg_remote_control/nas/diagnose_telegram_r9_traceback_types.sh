#!/bin/sh
# R9: privacy-preserving scheduler traceback audit. No raw lines or paths printed.
set -eu
python3 - <<'PY'
import collections,json,pathlib,re
p=pathlib.Path('/volume1/docker/RG_NAS_STATE/auto-deploy.log')
if p.is_symlink() or not p.is_file():
 print('LOG_UNAVAILABLE');raise SystemExit(1)
with p.open('rb') as f:
 f.seek(0,2); size=f.tell();f.seek(max(0,size-262144))
 lines=f.read().decode('utf-8','replace').splitlines()
exceptions=collections.Counter()
timeout_context=collections.Counter()
missing_context=collections.Counter()
for i,line in enumerate(lines):
 if re.search(r'^Traceback \(most recent call last\):',line):
  for nextline in lines[i+1:i+35]:
   m=re.match(r'^([A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*(?:Error|Exception|Exit|Interrupt))\s*:',nextline)
   if m:
    exceptions[m.group(1)]+=1;break
   if nextline.startswith('Traceback (most recent call last):'):break
 if re.search(r'timeout|timed out',line,re.I):
  for name,pattern in {
    'docker':r'docker|container',
    'git':r'git|github',
    'network':r'curl|http|connect|request|url',
    'python':r'python|pip|traceback',
    'scheduler':r'scheduler|tick|deploy',
  }.items():
   if re.search(pattern,line,re.I):timeout_context[name]+=1
 if re.search(r'no such file|FileNotFoundError',line,re.I):
  for name,pattern in {
    'docker':r'docker|container',
    'git':r'git|github',
    'python':r'python|pip',
    'shell':r'\.sh\b|/bin/sh',
    'state':r'heartbeat|state|lock|\.json',
  }.items():
   if re.search(pattern,line,re.I):missing_context[name]+=1
print('RG_R9_TRACEBACK_TYPES_READ_ONLY')
print(json.dumps({'exception_types':dict(exceptions),'timeout_contexts':dict(timeout_context),'missing_file_contexts':dict(missing_context),'lines_scanned':len(lines),'note':'Counts are matches, not root causes; uncategorized cases are possible.'},sort_keys=True))
print('SCOPE NO_RAW_LINES_NO_PATHS_NO_SECRETS_NO_MUTATIONS')
PY
