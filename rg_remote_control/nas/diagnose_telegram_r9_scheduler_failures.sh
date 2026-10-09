#!/bin/sh
# R9 safe scheduler log failure summary. Read only, no raw log output.
set -eu
python3 - <<'PY'
import collections,json,pathlib,re
p=pathlib.Path("/volume1/docker/RG_NAS_STATE/auto-deploy.log")
if p.is_symlink() or not p.is_file():print("LOG_UNAVAILABLE");raise SystemExit(1)
with p.open("rb") as f:
 f.seek(0,2);f.seek(max(0,f.tell()-131072))
 lines=f.read().decode("utf-8","replace").splitlines()
classes=[
 ("PYTHON_TRACEBACK",r"Traceback \(most recent call last\)"),
 ("TIMEOUT",r"timed out|timeout|TimeoutError"),
 ("PERMISSION",r"PermissionError|permission denied"),
 ("DOCKER",r"docker:|cannot connect to the Docker daemon"),
 ("HTTP_AUTH",r"(?<![0-9])(?:401|403)(?![0-9])|unauthorized"),
 ("HTTP_RATE_LIMIT",r"(?<![0-9])429(?![0-9])|rate.?limit"),
 ("MISSING_FILE",r"No such file or directory|FileNotFoundError"),
 ("IMPORT_ERROR",r"ModuleNotFoundError|ImportError"),
 ("DNS",r"Name or service not known|Temporary failure in name resolution"),
 ("CONNECTION",r"ConnectionError|Connection refused|ConnectTimeout"),
]
counts=collections.Counter()
for line in lines:
 for label,pattern in classes:
  if re.search(pattern,line,re.I):counts[label]+=1
print("RG_R9_SCHEDULER_FAILURE_CLASSIFICATION")
print(json.dumps(dict(counts),sort_keys=True))
print("LINES_SCANNED",len(lines))
print("SCOPE READ_ONLY_COUNTS_ONLY_NO_RAW_LOG_CONTENT")
PY
