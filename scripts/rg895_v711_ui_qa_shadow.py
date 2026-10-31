"""Read-only in-memory test of RG Studio QA-blocked state. Never writes installed modules."""
import ast,hashlib,json,sys,types
from pathlib import Path
APP=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit App')
sys.path.insert(0,str(APP))
p=APP/'rg_fullstream_manual_tab_v4.py'
s=p.read_text(encoding='utf-8-sig')
sha=hashlib.sha256(p.read_bytes()).hexdigest()
print('RGV711UI|ORIGINAL_SHA|'+sha,flush=True)
if sha!='27e9022b577b30c0db8463cd7734380d684605b9ea5856cb5b6471de669d2c46':
 raise RuntimeError('UNRECOGNIZED_INSTALLED_MANUAL_TAB')
changes=[
 ("if queue and state not in ('RUNNING','READY_FOR_MANUAL_REVIEW'):state='QUEUED'", "if queue and state not in ('RUNNING','READY_FOR_MANUAL_REVIEW','CONTENT_QA_BLOCKED'):state='QUEUED'"),
 ("    # V5.9: a previous RUNNING receipt is NOT proof of a live GPU worker.", "    if exists and (report.get('content_qa_status')=='BLOCKED_MISSING_EVIDENCE' or\n                   (report.get('content_qa_v65') or {}).get('content_qa')=='BLOCKED_MISSING_EVIDENCE'):\n        state='CONTENT_QA_BLOCKED'\n    # V5.9: a previous RUNNING receipt is NOT proof of a live GPU worker."),
 ("    elif state=='RUNNING':percent=None", "    elif state=='RUNNING':percent=None\n    if state=='CONTENT_QA_BLOCKED':percent=None"),
 ("'FAILED_NEEDS_REVIEW':'ПОМИЛКА ЕКСПОРТУ','STOPPED_BY_USER'", "'CONTENT_QA_BLOCKED':'БЛОК QA • ПРАВИЛА НЕ ПІДТВЕРДЖЕНО',\n                'FAILED_NEEDS_REVIEW':'ПОМИЛКА ЕКСПОРТУ','STOPPED_BY_USER'"),
 ("        elif snap['state']=='STOPPED_BY_USER':current=", "        elif snap['state']=='CONTENT_QA_BLOCKED':current='MP4 створено, але якість монтажу не підтверджена • відкрийте звіт QA'\n        elif snap['state']=='STOPPED_BY_USER':current=")
]
for old,new in changes:
 if s.count(old)!=1:raise RuntimeError('UI_PATCH_CONTEXT_NOT_UNIQUE:'+old[:35])
 s=s.replace(old,new,1)
ast.parse(s)
m=types.ModuleType('rg_fullstream_manual_v711_memory_only');m.__file__=str(p)
exec(compile(s,str(p),'exec'),m.__dict__)
actual=m.status_snapshot('895')
print('RGV711UI|REAL_895|'+json.dumps({k:actual.get(k) for k in ('state','progress_percent','video_exists','queue_exists')},ensure_ascii=True),flush=True)
if actual['state']!='CONTENT_QA_BLOCKED' or actual['progress_percent'] is not None:
 raise RuntimeError('QA_BLOCKED_NOT_VISIBLE_OR_STALE_PROGRESS')
print('RGV711UI|PASS|NO_INSTALLED_FILES_MODIFIED',flush=True)