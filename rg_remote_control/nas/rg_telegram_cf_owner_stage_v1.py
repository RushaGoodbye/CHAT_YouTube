#!/usr/bin/env python3
"""RG Telegram Cloudflare owner-switch source readiness, read-only production.
Fetch pinned PRIVATE repo source using existing NAS GitHub token, never print it.
Does not change running Workers/crons, no Telegram polling/sends, no deploy.
"""
import argparse,base64,hashlib,json,os,pathlib,re,subprocess,sys,tempfile,urllib.error,urllib.parse,urllib.request
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
GH_TOKEN=ROOT/"RG_SECRETS/github_token"
PIN="50204a1721a103206342f2e39faada53f02ef730"
REPO="RushaGoodbye/rasha-goodbye-news-bot"
FILES={"index.js":"cloudflare-alerts/src/index.js",
       "wrangler.toml":"cloudflare-alerts/wrangler.toml",
       "test-nas-moderation-owner.mjs":"cloudflare-alerts/scripts/test-nas-moderation-owner.mjs"}
STAGE=STATE/"cf_moderation_handoff_stage_v1"
PROD=ROOT/"RG_ALERTS_DEPLOY/cloudflare-alerts"
def out(status,**k):
 print(json.dumps({"status":status,"telegram_sends":0,"telegram_polls":0,
   "cloudflare_writes":0,"production_files_changed":False,**k},ensure_ascii=False),flush=True)
def contents(token,path):
 url="https://api.github.com/repos/"+REPO+"/contents/"+urllib.parse.quote(path,safe="/")+"?ref="+PIN
 req=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,
  "Accept":"application/vnd.github+json","User-Agent":"RG-NAS-Telegram-Owner-Staging/1"})
 try:
  with urllib.request.urlopen(req,timeout=16) as r:data=json.loads(r.read(500000))
 except urllib.error.HTTPError as e:raise RuntimeError("source_http_"+str(e.code)) from None
 except (urllib.error.URLError,ValueError,OSError):raise RuntimeError("source_download_failed") from None
 if not isinstance(data,dict) or data.get("encoding")!="base64":raise RuntimeError("source_invalid")
 raw=base64.b64decode(data.get("content",""),validate=False)
 if not raw or len(raw)>200000:raise RuntimeError("source_invalid_size")
 return raw
def validate(files):
 code=files["index.js"].decode("utf-8")
 toml=files["wrangler.toml"].decode("utf-8")
 test=files["test-nas-moderation-owner.mjs"].decode("utf-8")
 checks={
 "owner_guard":'moderationOwner === "nas"' in code and '"nas_moderation_owner"' in code,
 "default_cloudflare":'RG_MODERATION_RUNTIME_OWNER = "cloudflare"' in toml,
 "worker_name":'name = "rasha-goodbye-air-alerts"' in toml,
 "minute_cron_preserved":'crons = ["* * * * *"]' in toml,
 "alerts_untouched":'const alertPollTask = poll(env, ctx)' in code,
 "minute_silence_untouched":'maybePublishMinuteSilence(env, ctx, event?.scheduledTime)' in code,
 "existing_poll_present_in_fallback":': processTelegramModerationUpdates(env)' in code,
 "regression_test":'NAS_MODERATION_OWNER_SELECTIVE_HANDOFF_PASS' in test,
 }
 if not all(checks.values()):raise RuntimeError("owner_handoff_contract_failed")
 return checks
def selftest():
 fake={
 "index.js":b'const moderationOwner = env.x; moderationOwner === "nas" ? "nas_moderation_owner" : processTelegramModerationUpdates(env); const alertPollTask = poll(env, ctx); const silenceTask = maybePublishMinuteSilence(env, ctx, event?.scheduledTime);',
 "wrangler.toml":b'name = "rasha-goodbye-air-alerts"\nRG_MODERATION_RUNTIME_OWNER = "cloudflare"\ncrons = ["* * * * *"]',
 "test-nas-moderation-owner.mjs":b'NAS_MODERATION_OWNER_SELECTIVE_HANDOFF_PASS'
 }
 try:validate(fake)
 except RuntimeError:pass
 else:raise AssertionError("missing fallback accepted")
 out("CF_OWNER_PREDEPLOY_SELFTEST_PASS",fail_closed="PASS",network_calls=0)
def stage():
 if os.geteuid()!=0:raise RuntimeError("sudo_required")
 if not GH_TOKEN.is_file() or GH_TOKEN.is_symlink():raise RuntimeError("github_access_token_missing")
 token=GH_TOKEN.read_text("utf-8").strip()
 if not re.fullmatch(r"[A-Za-z0-9_-]{20,300}",token):raise RuntimeError("github_access_token_invalid")
 if STAGE.is_symlink():raise RuntimeError("stage_symlink")
 if not PROD.is_dir() or (PROD/"src/index.js").is_symlink() or (PROD/"wrangler.toml").is_symlink():
  raise RuntimeError("existing_worker_source_missing")
 pending=ROOT/"RG_SECRETS/rg_nas_telegram_cutover_enabled"
 if pending.exists():raise RuntimeError("nas_cutover_already_enabled")
 files={name:contents(token,path) for name,path in FILES.items()}
 del token
 checks=validate(files)
 existing=(PROD/"src/index.js").read_text("utf-8")
 if 'const alertPollTask = poll(env, ctx)' not in existing or 'processTelegramModerationUpdates(env)' not in existing:
  raise RuntimeError("local_worker_source_not_expected")
 STAGE.mkdir(mode=0o700,parents=True,exist_ok=True)
 if STAGE.stat().st_mode&0o077:os.chmod(STAGE,0o700)
 for name,value in files.items():
  tmp=STAGE/("."+name+".tmp")
  if tmp.is_symlink():raise RuntimeError("tmp_symlink")
  tmp.write_bytes(value);os.chmod(tmp,0o600);os.replace(tmp,STAGE/name)
 report={
  "status":"CF_OWNER_GUARD_STAGE_READY","upstream_commit":PIN,
  "checks":checks,"local_production_source_sha256_16":hashlib.sha256(existing.encode()).hexdigest()[:16],
  "new_index_sha256_16":hashlib.sha256(files["index.js"]).hexdigest()[:16],
  "new_config_default_owner":"cloudflare","live_worker_owner_not_changed":True,
  "production_crons_not_changed":True,
  "cutover_allowed":False,"telegram_sends":0,"telegram_polls":0,"cloudflare_writes":0}
 path=STAGE/"preflight_report.json"
 path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n","utf-8")
 os.chmod(path,0o600)
 print(json.dumps(report,ensure_ascii=False))
def main():
 p=argparse.ArgumentParser();p.add_argument("mode",choices=("selftest","stage"));a=p.parse_args()
 if a.mode=="selftest":selftest()
 else:stage()
if __name__=="__main__":
 try:main()
 except Exception as e:
  reason=str(e) if str(e) in {"github_access_token_missing","github_access_token_invalid",
   "stage_symlink","existing_worker_source_missing","nas_cutover_already_enabled",
   "owner_handoff_contract_failed","local_worker_source_not_expected","source_invalid",
   "source_download_failed","source_invalid_size"} or str(e).startswith("source_http_") else type(e).__name__
  out("BLOCKED",reason=reason)
  sys.exit(1)
