#!/usr/bin/env python3
"""NEWS2 batch Nov14: visual-only moderation, special captions, single poll sources,
and dormant API-key-gated GPT Image illustrator. ALL preflight before any change.

Cloudflare source patch does not deploy to Cloudflare; separate version
deployment and live verification required. No Telegram/Image API calls.
"""
import hashlib,json,os,pathlib,subprocess,sys
scripts=[
 ('visual','/tmp/rg_news2_visual_only_and_special_caption_atomic_20261114.py',
  'e6e182851a7eee4baecdd682c9a991c9f3610f44'),
 ('cloudflare','/tmp/rg_news2_cf_special_footers_single_poll_20261114.py',
  '90379cfe407949078fc0dfcc7096de4a7f54681f'),
 ('image','/tmp/rg_news2_ai_illustration_hook_install_20261114.py',
  '51e7ecf086f877d36abe85199887be310d9c419a')
]
class Stop(ValueError):pass
def git_blob(b):
 return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
def pinned():
 if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
 for name,path,digest in scripts:
  p=pathlib.Path(path)
  if p.is_symlink() or not p.is_file() or git_blob(p.read_bytes())!=digest:
   raise Stop('STAGED_SOURCE_CHANGED_'+name)
def call(p,mode):
 cp=subprocess.run(['/usr/bin/python3',p,mode],capture_output=True,text=True,timeout=190)
 found=None
 for line in cp.stdout.splitlines():
  if line.startswith('{'):
   try:found=json.loads(line)
   except ValueError:continue
 if cp.returncode or not isinstance(found,dict) or found.get('status') not in (
      'PREFLIGHT_PASS','APPLIED_QA_PASS','SOURCE_PATCHED_QA_PASS_DEPLOY_PENDING',
      'APPLIED_QA_PASS_KEY_GATED'):
  raise Stop('MODULE_'+pathlib.Path(p).name+'_'+mode+'_'+str((found or {}).get('reason','FAILED'))[:120])
 return found
def run(mode):
 pinned()
 if mode=='preflight':
  report={}
  for k,p,h in scripts:report[k]=call(p,'preflight')['status']
  return {'status':'BATCH_PREFLIGHT_PASS','modules':report,
   'telegram_calls':0,'publications':0,'image_api_calls':0}
 if mode=='apply':
  # No changes if any preflight fails.
  for k,p,h in scripts:call(p,'preflight')
  outcomes={}
  for k,p,h in scripts:outcomes[k]=call(p,'apply')['status']
  return {'status':'BATCH_LOCAL_SOURCES_APPLIED_QA_PASS',
   'components':outcomes,
   'cloudflare_remote_deploy':'PENDING_SEPARATE_VERIFICATION',
   'gpt_image':'KEY_GATED',
   'telegram_calls':0,'publications':0,'image_api_calls':0}
 raise Stop('UNSUPPORTED_MODE')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:
   assert len(scripts)==3 and all(len(s[2])==40 for s in scripts)
   print('RG_NEWS2_THREE_FIXES_BATCH_INSTALLER_SELFTEST_PASS')
  else:
   print(json.dumps(run(sys.argv[1] if len(sys.argv)==2 else 'invalid'),sort_keys=True))
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:200],
    'telegram_calls':0,'publications':0,'image_api_calls':0}))
  raise SystemExit(2)
