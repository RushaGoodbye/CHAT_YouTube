#!/usr/bin/env python3
"""Conservatively sanitize one staged NEWS RG draft. No Telegram APIs."""
import os,sys,json,pathlib,tempfile
D=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator/news_rg_private_review_staging')
ID='9573d12d2cdedba1a829943a'
def main():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 p=D/(ID+'.json')
 if not p.is_file() or p.is_symlink():raise RuntimeError('DRAFT_NOT_FOUND')
 x=json.loads(p.read_text(encoding='utf-8'))
 if x.get('draft_id')!=ID or x.get('telegram_delivery')!='NOT_SENT' or x.get('public_publication')!='OFF':raise RuntimeError('STAGING_INVARIANT_FAIL')
 old=x['proposed_text']
 text=old.replace('надходжуваний дефіцит','очікуваний дефіцит')
 text=text.replace('🇺🇦 INSIDER UA | Прислати контент','').strip()
 if text==old:raise RuntimeError('UNEXPECTED_INPUT_NO_CHANGE')
 if not (100<len(text)<900):raise RuntimeError('INVALID_EDITED_LENGTH')
 x['proposed_text']=text
 x['editorial_status']='HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED'
 fd,tmp=tempfile.mkstemp(dir=str(D),prefix='.newsrg_edit_')
 try:
  os.fchmod(fd,0o600)
  with os.fdopen(fd,'w',encoding='utf-8') as h:
   json.dump(x,h,ensure_ascii=False,indent=2);h.flush();os.fsync(h.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 print(json.dumps({'status':'EDITED_DRAFT_READY_FOR_PRIVATE_REVIEW','draft_id':ID,'text':text,'fact_checked':False,'telegram_calls':0,'publications':0},ensure_ascii=False))
if __name__=='__main__':
 try:main()
 except Exception as e:print(json.dumps({'status':'SAFE_STOP','reason':str(e),'telegram_calls':0,'publications':0}));sys.exit(2)
