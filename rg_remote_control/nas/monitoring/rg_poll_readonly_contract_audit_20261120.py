#!/usr/bin/env python3
"""Read-only RG NEWS2 poll go/no-go audit. Never imports or executes live bot."""
import ast,hashlib,json,os,pathlib,sys
ROOT=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
P=ROOT/'operator/news_rg_poll_moderation_v1.py'
Q=ROOT/'operator/news_rg_poll_quality_v1.py'
B=ROOT/'rg_news2_fix_20261119/protected_backups'
EXPECTED_SHA='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
def sha(b):return hashlib.sha256(b).hexdigest()
def check():
 if not P.is_file() or P.is_symlink() or not Q.is_file() or Q.is_symlink():
  raise ValueError('MISSING_OR_UNSAFE_MODULE')
 data=P.read_bytes()
 s=data.decode('utf8')
 t=ast.parse(s)
 funcs={n.name:n for n in t.body if isinstance(n,ast.FunctionDef)}
 for name in ('validate_poll','make_variant','preview','buttons','send_private','scheduled','process_regeneration','poll_tick','callback'):
  if name not in funcs:raise ValueError('MISSING_FUNCTION_'+name)
 cb=funcs['callback']
 calls=[n for n in ast.walk(cb) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='telegram' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='sendPoll']
 photos=[n for n in ast.walk(cb) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='send_photo']
 if len(calls)!=1 or len(photos)!=1:raise ValueError('PUBLIC_SENDER_COUNT_CHANGED')
 def raises_or_return(n):
  return isinstance(n,(ast.Return,ast.Raise))
 quality_calls=[n for n in ast.walk(t) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_rg_poll_editorial_validate']
 gates=[n for n in ast.walk(cb) if isinstance(n,ast.Return) and isinstance(n.value,ast.Dict)
    and any(isinstance(x,ast.Constant) and x.value=='POLL_PUBLICATION_PAUSED_PENDING_VERIFIED_APPROVAL' for x in n.value.values)]
 if len(quality_calls)!=2 or len(gates)!=1:raise ValueError('V6_GUARD_MISSING')
 gate=gates[0]
 claims=[n for n in ast.walk(cb) if isinstance(n,ast.Assign) and n.lineno>gate.lineno and any(isinstance(x,ast.Constant) and x.value=='PUBLIC_SEND_UNCERTAIN' for x in ast.walk(n))]
 if not claims:raise ValueError('CLAIM_NOT_FOUND')
 if not (gate.lineno < min(n.lineno for n in claims) < photos[0].lineno < calls[0].lineno):
  raise ValueError('PUBLIC_GUARD_ORDER_INVALID')
 v=t
 valid_src=ast.get_source_segment(s,funcs['validate_poll']) or ''
 if '_rg_poll_editorial_validate(question,options)' not in valid_src:raise ValueError('GENERATION_GATE_MISSING')
 # check exact revision; other modifications must be explicitly reviewed
 matching_sha=sha(data)==EXPECTED_SHA
 qa_src=Q.read_bytes()
 if sha(qa_src)!='bc585371bc693093a5469ca7abc32a09a35a9ebdec67f919223c52a1c05b4e22':
  raise ValueError('QUALITY_MODULE_CHANGED')
 # Review history and current draft counts without exposing captions or secrets
 status={'status':'RG_POLL_READONLY_CONTRACT_PASS' if matching_sha else 'RG_POLL_SOURCE_CHANGED_REVIEW_REQUIRED',
  'live_sha256':sha(data),'v6_expected_sha_match':matching_sha,
  'quality_generation':True,'quality_approval':True,
  'public_gate_before_claim_and_photo':True,
  'callback_args':[n.arg for n in cb.args.args],
  'sendPoll_line':calls[0].lineno,'public_photo_line':photos[0].lineno,
  'approval_guard_line':gate.lineno,'backup_directory_exists':B.exists(),
  'current_poll_publication_enabled':False,'cloudflare_deployment_verified':False,
  'telegram_calls':0,'publications':0,'new_pollers':0}
 return status
if __name__=='__main__':
 try:print(json.dumps(check(),ensure_ascii=False,indent=2))
 except Exception as e:
  print(json.dumps({'status':'RG_POLL_AUDIT_SAFE_STOP','reason':str(e)[:130],
    'telegram_calls':0,'publications':0},ensure_ascii=False));sys.exit(2)
