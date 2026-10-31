"""Read-only RG895 intro scanner API verification; no media edits."""
import hashlib,inspect,json,sys,time
from pathlib import Path
APP=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit App')
DATA=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit Data\fullstream_v2\895')
sys.path.insert(0,str(APP))
plan=json.loads((DATA/'processing_plan.json').read_text(encoding='utf-8-sig'))
def emit(k,v):print('RGINTROVERIFY|'+k+'|'+json.dumps(v,ensure_ascii=True,default=str),flush=True)
for name in ['rg_fullstream_policy_v70.py','rg_fullstream_auto_v2.py','rg_fullstream_detectors_v2.py','rg_fullstream_qa_v65.py']:
 p=APP/name
 if not p.is_file():
  emit('FILE',{'name':name,'exists':False});continue
 lines=p.read_text(encoding='utf-8-sig').splitlines()
 relevant=[]
 for i,line in enumerate(lines):
  if any(k in line for k in ('def intro_color_host_start','max_search=','intro_color_host_start(','scan_popups(','def scan_popups','def audit_report','CONTENT_QA_BLOCKED')):
   relevant.append({'line':i+1,'code':line.strip()[:160]})
 emit('FILE',{'name':name,'exists':True,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'relevant':relevant[:20]})
from rg_fullstream_policy_v70 import intro_color_host_start
emit('SIGNATURE',str(inspect.signature(intro_color_host_start)))
start=time.monotonic()
try:
 result=intro_color_host_start(plan['video'],11480.17,max_search=935)
 emit('TEST',{'result':result,'elapsed_seconds':round(time.monotonic()-start,1)})
except Exception as e:
 emit('TEST_ERROR',{'type':type(e).__name__,'message':str(e)[:250]})
 raise
