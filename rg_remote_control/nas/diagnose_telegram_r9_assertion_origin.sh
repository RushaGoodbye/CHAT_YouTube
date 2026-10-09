#!/bin/sh
# Read-only R9: classify exact traceback origin without printing raw paths, args or secrets.
set -eu
python3 - <<'PY'
from pathlib import Path
from collections import Counter
import json,re
p=Path("/volume1/docker/RG_NAS_STATE/auto-deploy.log")
if not p.is_file() or p.is_symlink():print("LOG_UNAVAILABLE");raise SystemExit(1)
with p.open("rb") as f:
 f.seek(0,2);f.seek(max(0,f.tell()-262144))
 lines=f.read().decode("utf8","replace").splitlines()
origins=Counter()
for i,line in enumerate(lines):
 if line.strip()!="Traceback (most recent call last):":continue
 block=lines[i+1:i+45]
 if not any(re.match(r"^AssertionError(?:\s*:|\s*$)",l) for l in block):continue
 # Only emit fixed categories; never extract actual paths.
 category="unknown"
 for l in block:
  if "File " not in l:continue
  ll=l.lower()
  if "docker" in ll:category="docker_related"
  elif "test" in ll or "selftest" in ll:category="selftest"
  elif "deploy" in ll:category="deployment"
  elif "telegram" in ll:category="telegram"
  elif "scheduler" in ll:category="scheduler"
  elif category=="unknown":category="other_python"
 origins[category]+=1
print("RG_R9_ASSERTION_ORIGINS")
print(json.dumps({"assertion_tracebacks_by_context":dict(origins),"sample_lines":len(lines)},sort_keys=True))
print("NO_RAW_PATHS_NO_NETWORK_NO_MUTATIONS")
PY
