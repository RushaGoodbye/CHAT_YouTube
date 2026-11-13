#!/usr/bin/env python3
"""RG NEWS2 Stage3 factual evidence inventory. No Telegram API, no file writes."""
from pathlib import Path
import ast,json,re,hashlib,sqlite3,datetime
B=Path('/volume1/docker/RG_TELEGRAM_NEWS_2');O=B/'operator'
H=O/'news_rg_stability_healthcheck_v1.py'
P=O/'news_rg_private_multipart_receipts_v1'
out={}
def safe_name(s):
 return bool(re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}',str(s)))
def keys_only(path):
 try:
  if path.is_symlink() or not path.is_file() or path.stat().st_size>1024*1024:return None
  d=json.loads(path.read_text())
  return sorted(k for k in d if safe_name(k)) if isinstance(d,dict) else None
 except Exception:return None
def inspect_code():
 t=ast.parse(H.read_text())
 for func in (n for n in t.body if isinstance(n,ast.FunctionDef) and n.name in ('public_queue','private_queue','source_scan')):
  strings=[]
  for node in ast.walk(func):
   if isinstance(node,ast.Constant) and isinstance(node.value,str):
    s=node.value
    if s.endswith(('.json','.sqlite3')) or ('receipt' in s.lower() and safe_name(s)):
     strings.append(s[:90])
  out[func.name+'_file_literals']=list(dict.fromkeys(strings))[:25]
def receipt_evidence():
 uncertain=[]
 for f in P.glob('*.json'):
  k=keys_only(f)
  if not k:continue
  # Read only targeted status; do not include draft_id, chat_id, message bodies or tokens.
  try:
   d=json.loads(f.read_text())
   if d.get('status') in ('UNCERTAIN_NO_RETRY','SENDING_UNCERTAIN','HTTP_REJECTED_NO_RETRY'):
    uncertain.append({'receipt_hash':hashlib.sha256(f.name.encode()).hexdigest()[:12],
      'status':d.get('status'),'available_fields':k,
      'error_class':str(d.get('error_class',''))[:35] if safe_name(d.get('error_class','')) else 'REDACTED'})
  except Exception:pass
 out['unresolved_receipt_schema']=uncertain[:12]
def public_ledger():
 # Inventory publication files by name patterns; never open content unless strict JSON summary.
 roots=[O/'news_rg_publication_receipts_v1', O/'news_rg_public_receipts_v1',O/'news_rg_publication_receipts',
        O/'news_rg_approved_publication_receipts_v1',O/'news_rg_publication_ledger_v1']
 out['publication_directory_candidates']=[]
 for p in roots:
  if p.is_dir() and not p.is_symlink():
   files=list(p.glob('*.json'))
   out['publication_directory_candidates'].append({'dirname':p.name,'json_files':len(files),
    'sample_fields':keys_only(files[0]) if files else []})
def routes():
 paths=['/volume1/docker/RG_NAS_MCP/ALEXPC','/volume1/docker/RG_TELEGRAM_NEWS_EXPORT/rg_news_health_public.json']
 out['nas_paths']=[{'name':Path(p).name,'exists':Path(p).exists()} for p in paths]
 out['public_runner_shutdown_allowed']=False
 out['private_runner_bridge_verified_operations']=['inspect_auto_edit_files_generic']
 out['legacy_routes_not_ported']=['rg-remote-control.yml','rg-nas-alexpc-agent-control.yml']
 out['publications_api_verified']=False
 out['telegram_api_calls']=0
 out['production_writes']=0
try:inspect_code()
except Exception as e:out['code_inspection_error']=type(e).__name__
try:receipt_evidence()
except Exception as e:out['receipt_error']=type(e).__name__
try:public_ledger()
except Exception as e:out['ledger_error']=type(e).__name__
routes()
print(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True))
