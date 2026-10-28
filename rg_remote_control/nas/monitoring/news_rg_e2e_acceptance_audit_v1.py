#!/usr/bin/env python3
"""NEWS RG: read-only, one-card end-to-end confirmation.
No Telegram APIs, no getUpdates, no DB mutations, no publication actions.
"""
import os,sys,json,pathlib,time,re,stat
BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=BASE/'operator'
ID='e793f4cd55c5246022bf86e8'
EXPECTED_MESSAGE=8050
def load_json(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size>40000:
        raise RuntimeError('FILE_UNSAFE_OR_MISSING_'+path.name)
    return json.loads(path.read_text(encoding='utf-8'))
def check():
    if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
    rec=load_json(OP/'news_rg_private_multipart_receipts_v1'/(ID+'.json'))
    if rec.get('status')!='PRIVATE_SENT_CONFIRMED' or rec.get('draft_id')!=ID or rec.get('message_id')!=EXPECTED_MESSAGE:
        raise RuntimeError('TELEGRAM_RECEIPT_UNVERIFIED')
    staged=load_json(OP/'news_rg_private_review_staging'/(ID+'.json'))
    if staged.get('public_publication')!='OFF' or staged.get('draft_id')!=ID:
        raise RuntimeError('STAGING_PUBLICATION_GATE_NOT_OFF')
    mod=BASE/'rg_moderation.py'
    hook=OP/'news_rg_editorial_callbacks_v1.py'
    if not mod.is_file() or mod.is_symlink() or not hook.is_file() or hook.is_symlink():
        raise RuntimeError('CALLBACK_MODULE_MISSING')
    if '# NEWS_RG_EDITORIAL_HOOK_V1' not in mod.read_text():
        raise RuntimeError('EDITORIAL_HOOK_MISSING')
    text=hook.read_text()
    if 'ne1:(accept|reject)' not in text or 'EDITORIAL_ACCEPTED_NO_PUBLICATION' not in text:
        raise RuntimeError('EDITORIAL_CALLBACK_CONTRACT_CHANGED')
    result={'schema':'NEWS_RG_E2E_ACCEPTANCE_READONLY_V1',
            'draft_id':ID,'telegram_message_id':EXPECTED_MESSAGE,
            'private_delivery':'CONFIRMED','editorial_hook':'INSTALLED',
            'public_publication':'OFF','read_only':True,'telegram_calls':0,
            'pollers_started':0,'db_writes':0,'publications':0}
    dec=OP/'news_rg_editorial_decisions_v1'/(ID+'.json')
    if dec.exists():
        d=load_json(dec)
        if d.get('draft_id')!=ID or d.get('telegram_message_id')!=EXPECTED_MESSAGE or d.get('public_publication')!='OFF':
            raise RuntimeError('EDITORIAL_DECISION_INCONSISTENT')
        if d.get('decision') not in ('editorially_accepted_not_published','editorially_rejected'):
            raise RuntimeError('EDITORIAL_DECISION_NOT_VALID')
        result['editorial_decision']=d['decision']
        result['status']='EDITORIAL_DECISION_CONFIRMED'
    else:
        result['editorial_decision']='NOT_YET_RECORDED'
        result['status']='WAITING_FOR_EDITORIAL_CALLBACK'
    log=OP/'callback_v29.log'
    if log.is_file() and not log.is_symlink():
        result['callback_log_age_sec']=max(0,int(time.time()-log.stat().st_mtime))
        result['callback_log_fresh']=result['callback_log_age_sec']<300
    else:
        result['callback_log_age_sec']=None
        result['callback_log_fresh']=False
    handler=OP/'callback_v29.py'
    if handler.is_file() and not handler.is_symlink():
        src=handler.read_text()
        result['callback_owner_present']=True
        result['callback_owner_process_callback_reference']='process_callback' in src
    else:
        result['callback_owner_present']=False
        result['callback_owner_process_callback_reference']=False
    return result
if __name__=='__main__':
    try:
        if sys.argv[1:]==['selftest']:
            assert ID and len(ID)==24 and EXPECTED_MESSAGE>0
            print('NEWS_RG_E2E_AUDIT_SELFTEST_PASS')
        elif sys.argv[1:]==['audit']:
            print(json.dumps(check(),ensure_ascii=False,indent=2,sort_keys=True))
        else:raise RuntimeError('BAD_COMMAND')
    except Exception as e:
        print(json.dumps({'status':'SAFE_STOP','error_class':str(e)[:130],'publications':0,'telegram_calls':0},ensure_ascii=False))
        sys.exit(2)
