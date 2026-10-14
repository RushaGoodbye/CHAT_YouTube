#!/usr/bin/env python3
"""Verify deployed Cloudflare moderation guard without triggering NAS bot cutover.
Read-only; does not mint a deployed.json receipt or start getUpdates.
"""
import importlib.util, pathlib, json, re, urllib.request, urllib.error, sys, hashlib
R=pathlib.Path('/volume1/docker')
P=R/'RG_TELEGRAM_STATE/rg_telegram_cf_selective_moderation_handoff_v1.py'
def main():
 spec=importlib.util.spec_from_file_location('rg_cf_handoff',str(P))
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 token=m.module().env_token()
 live_owner=m.owner(token)
 crons={n:m.cron(token,n) for n in (m.WORKER,)+m.OTHER}
 required={'rasha-goodbye-air-alerts':['* * * * *'],'rasha-goodbye-content-hub':['* * * * *'],'rasha-goodbye-video-scanner':[]}
 if live_owner!='nas' or crons!=required:
  raise RuntimeError('LIVE_CF_OWNER_OR_CRONS_MISMATCH')
 url=f'https://api.cloudflare.com/client/v4/accounts/{m.CF_ACCOUNT}/workers/scripts/{m.WORKER}'
 req=urllib.request.Request(url,headers={'Authorization':'Bearer '+token,'User-Agent':'RG-Handoff-Remote-Attestation/1'})
 with urllib.request.urlopen(req,timeout=20) as response:
  if not response.headers.get('Content-Type','').lower().startswith(('application/javascript','text/javascript','multipart/form-data')):
   raise RuntimeError('UNRECOGNIZED_REMOTE_SCRIPT_MEDIA_TYPE')
  remote=response.read(4_000_001)
 if len(remote)>4_000_000:raise RuntimeError('REMOTE_WORKER_TOO_LARGE')
 source=remote.decode('utf-8','replace')
 checks={
  'has_owner_variable':bool(re.search(r'RG_MODERATION_RUNTIME_OWNER',source)),
  'has_nas_skip':bool(re.search(r'nas_moderation_owner',source)),
  'has_conditional_branch':bool(re.search(r'moderationOwner\s*===\s*[\x22\x27]nas[\x22\x27]',source)),
  'has_legacy_handler':bool(re.search(r'processTelegramModerationUpdates\s*\(',source))
 }
 # String tests alone are not proof that other async paths or hosts cannot poll.
 guarded=all(checks.values())
 print(json.dumps({'status':'LIVE_WORKER_GUARD_OBSERVED' if guarded else 'BLOCKED',
  'worker_sha256':hashlib.sha256(remote).hexdigest(),
  'checks':checks,'moderation_owner':'nas','scanner_cron':[],
  'independent_polling_exclusivity_proven':False,
  'deployed_receipt_written':False,'nas_gate_opened':False,'telegram_sends':0},ensure_ascii=False))
 if not guarded:sys.exit(1)
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'BLOCKED','error_type':type(e).__name__},ensure_ascii=False));sys.exit(1)
