#!/usr/bin/env python3
"""RG selective moderation: non-mutating Cloudflare Worker build diagnosis.
Reads current NAS source via a read-only Docker bind, copies it only INSIDE
an ephemeral container, then reproduces npm, JS, safety and Wrangler dry-run.
NEVER passes Cloudflare/Telegram secrets or performs a remote deploy.
Python 3.8 compatible. Does not modify production source, cron or NAS gate.
"""
import argparse,importlib.util,json,os,pathlib,re,subprocess,sys
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
WORKER=ROOT/"RG_ALERTS_DEPLOY/cloudflare-alerts"
GATE=ROOT/"RG_SECRETS/rg_nas_telegram_cutover_enabled"
CF_FREEZE=ROOT/"RG_SECRETS/rg_cf_moderation_handoff_freeze"
PAUSE=ROOT/"RG_SECRETS/rg_cloudflare_migration_pause"
STAGES=[
 ("SOURCE_COPY","mkdir -p /tmp/rg-build-check && cp -a /readonly/. /tmp/rg-build-check/"),
 ("NPM_INSTALL","npm install --no-audit --no-fund"),
 ("JS_SYNTAX","node --check src/index.js && node --check src/calendar-entry.js"),
 ("SAFETY_TEST","node scripts/test-safety-barrier.mjs"),
 ("WRANGLER_DRY_RUN","npx --no-install wrangler deploy --dry-run --outdir dist"),
]
def emit(status,**k):
 print(json.dumps({"status":status,"telegram_polls":0,"telegram_sends":0,
  "cloudflare_writes":0,"production_source_writes":0,"nas_gate_opened":False,**k},
  ensure_ascii=False),flush=True)
def redacted_line(text):
 line=re.sub(r"(?i)(Bearer\s+)[^\s]+",r"\1[REDACTED]",text)
 line=re.sub(r"(?i)((?:token|api[_-]?key|secret|password)[\s=:\"']+)[^\s,\"']+",
             r"\1[REDACTED]",line)
 line=re.sub(r"(?i)gh[psu]_[a-z0-9]{16,}","[REDACTED]",line)
 line=re.sub(r"(?i)sk-[a-z0-9_-]{12,}","[REDACTED]",line)
 line=re.sub(r"(?i)(?:https?://)[^/@\s]+:[^/@\s]+@","https://[REDACTED]@",line)
 return line[:200]
def diagnose():
 if os.geteuid()!=0:raise RuntimeError("SUDO_REQUIRED")
 if GATE.exists():raise RuntimeError("NAS_GATE_ALREADY_ENABLED")
 if PAUSE.exists():raise RuntimeError("FULL_CLOUDFLARE_PAUSE_ACTIVE")
 if not CF_FREEZE.is_file():raise RuntimeError("SELECTIVE_FREEZE_MISSING")
 if WORKER.is_symlink() or not (WORKER/"src/index.js").is_file():
  raise RuntimeError("ALERT_WORKER_SOURCE_MISSING")
 if not (WORKER/"wrangler.toml").is_file():
  raise RuntimeError("ALERT_WORKER_CONFIG_MISSING")
 sc=STATE/"rg_telegram_cf_selective_scanner_stop_v1.py"
 if not sc.is_file() or sc.is_symlink():raise RuntimeError("SCANNER_HELPER_NOT_INSTALLED")
 spec=importlib.util.spec_from_file_location("rg_diag_scanner",str(sc))
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 docker=module.docker_cli()
 engine=module.docker_daemon(docker)
 command=["set -eu","cd /tmp/rg-build-check"]
 for name,shell in STAGES:
  command.append('printf "\\nRG_DIAG_STAGE_BEGIN:%s\\n" '+name)
  command.append(shell)
  command.append('printf "RG_DIAG_STAGE_PASS:%s\\n" '+name)
 # SOURCE_COPY must happen before cd, so override script.
 shell=["set -eu"]
 for name,step in STAGES:
  shell.append('printf "\\nRG_DIAG_STAGE_BEGIN:%s\\n" '+name)
  if name=="SOURCE_COPY":shell.append(step+"\ncd /tmp/rg-build-check")
  else:shell.append(step)
  shell.append('printf "RG_DIAG_STAGE_PASS:%s\\n" '+name)
 cmd=[docker,"run","--rm","--network","bridge",
      "-v",str(WORKER)+":/readonly:ro","-w","/tmp",
      "node:22-bookworm-slim","sh","-lc","\n".join(shell)]
 emit("CF_WORKER_LOCAL_DIAGNOSTIC_STARTED",docker_cli=docker,docker_engine=engine,
  stages=[name for name,_ in STAGES],has_cloudflare_env=False,
  source_mount="READ_ONLY",container_workdir="EPHEMERAL",
  all_cloudflare_crons_unchanged=True)
 try:
  done=subprocess.run(cmd,capture_output=True,text=True,timeout=360)
 except subprocess.TimeoutExpired:
  emit("CF_WORKER_LOCAL_DIAGNOSTIC_FAILED",reason="DOCKER_BUILD_TIMEOUT",
       safe_to_repeat_diagnostic=True)
  return
 except OSError:
  emit("CF_WORKER_LOCAL_DIAGNOSTIC_FAILED",reason="DOCKER_EXEC_FAILED",
       safe_to_repeat_diagnostic=True)
  return
 result=(done.stdout or "")+"\n"+(done.stderr or "")
 beginnings=re.findall(r"RG_DIAG_STAGE_BEGIN:([A-Z_]+)",result)
 passed=re.findall(r"RG_DIAG_STAGE_PASS:([A-Z_]+)",result)
 stage=next((name for name in beginnings if name not in passed),None)
 if done.returncode==0 and len(passed)==len(STAGES):
  emit("CF_WORKER_LOCAL_BUILD_PASS",stages_passed=passed,
   result="ALL_LOCAL_BUILD_STEPS_PASSED",
   reminder="remote Cloudflare deployment/permissions not tested")
  return
 failing=stage or "DOCKER_STARTUP"
 lines=[redacted_line(x.strip()) for x in result.splitlines()
       if x.strip() and not x.startswith("RG_DIAG_STAGE_")]
 tail=[x for x in lines[-14:] if x][:14]
 reason="WORKER_LOCAL_"+failing+"_FAILED"
 low=result.lower()
 if any(k in low for k in ("cannot find module","module not found","could not resolve")):
  reason="NODE_MISSING_DEPENDENCY"
 elif "no such file or directory" in low:
  reason="MISSING_WORKER_ASSET_OR_SOURCE"
 elif "network" in low and "npm" in low:
  reason="NPM_NETWORK_FAILURE"
 emit("CF_WORKER_LOCAL_DIAGNOSTIC_FAILED",reason=reason,
  failed_stage=failing,completed_stages=passed,
  exit_code=done.returncode,log_tail_sanitized=tail,
  reminder="remote Cloudflare deploy was not attempted")
def selftest():
 assert [x[0] for x in STAGES]==[
  "SOURCE_COPY","NPM_INSTALL","JS_SYNTAX","SAFETY_TEST","WRANGLER_DRY_RUN"]
 assert redacted_line("Authorization Bearer ABCDEF")=="Authorization Bearer [REDACTED]"
 assert "[REDACTED]" in redacted_line("token=secret123")
 assert "node scripts/test-safety-barrier.mjs" in dict(STAGES)["SAFETY_TEST"]
 emit("CF_WORKER_LOCAL_DIAGNOSTIC_SELFTEST_PASS",network_calls=0)
if __name__=="__main__":
 try:
  p=argparse.ArgumentParser();p.add_argument("mode",choices=("selftest","diagnose"))
  args=p.parse_args()
  if args.mode=="selftest":selftest()
  else:diagnose()
 except Exception as ex:
  msg=str(ex)
  if not re.fullmatch(r"[A-Z0-9_]{3,100}",msg):msg=type(ex).__name__
  emit("BLOCKED",reason=msg)
  sys.exit(1)
