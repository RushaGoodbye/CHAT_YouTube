#!/usr/bin/env python3
"""Read-only NEWS RG private-card 8054 -> public post audit.

Never sends, polls, publishes, writes state, or invokes the scheduler. Checks
the existing NAS receipts, editorial callback and publisher launch evidence.
"""
import os,sys,json,time,pathlib,datetime
BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=BASE/'operator'
TARGET_MESSAGE=8054
EXPECTED_CHANNEL=-1001755891079
def safe_json(path):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>25000:return None
        v=json.loads(path.read_text(encoding='utf8'))
        return v if isinstance(v,dict) else None
    except (OSError,ValueError):return None
def age(t):
    if not isinstance(t,(int,float)) or isinstance(t,bool) or not 1700000000<t<time.time()+3600:
        return None
    return round(max(0,(time.time()-t)/60),2)
def marker(path):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>100:return None
        return float(path.read_text(encoding='utf8').strip())
    except (OSError,ValueError):return None
def log_last(path):
    try:
        if path.is_symlink() or not path.is_file():return {'present':False}
        with path.open('rb') as stream:
            stream.seek(max(0,path.stat().st_size-30000))
            lines=stream.read().decode('utf8','replace').splitlines()[-15:]
        for line in reversed(lines):
            try:
                val=json.loads(line)
                if isinstance(val,dict):
                    return {'present':True,'status':str(val.get('status','UNKNOWN'))[:80],
                            'message_id':val.get('message_id') if isinstance(val.get('message_id'),int) else None,
                            'age_minutes':age(path.stat().st_mtime)}
            except ValueError:continue
        return {'present':True,'status':'NO_STRUCTURED_RECEIPT','age_minutes':age(path.stat().st_mtime)}
    except OSError:return {'present':True,'status':'LOG_READ_ERROR'}
def find_card():
    directory=OP/'news_rg_private_multipart_receipts_v1'
    if not directory.is_dir() or directory.is_symlink():raise RuntimeError('PRIVATE_RECEIPTS_UNAVAILABLE')
    found=[]
    for path in directory.glob('*.json'):
        receipt=safe_json(path)
        if receipt and receipt.get('message_id')==TARGET_MESSAGE and receipt.get('status')=='PRIVATE_SENT_CONFIRMED':
            if len(path.stem)!=24 or any(c not in '0123456789abcdef' for c in path.stem):
                raise RuntimeError('INVALID_DRAFT_FILENAME')
            found.append((path.stem,receipt))
    if len(found)!=1:raise RuntimeError('CARD_8054_RECEIPT_'+('MISSING' if not found else 'DUPLICATE'))
    return found[0]
def classify(dec,pub,receipt,activation):
    if dec is None:return 'CALLBACK_DECISION_NOT_RECORDED'
    decision=dec.get('decision')
    if decision=='editorially_rejected':return 'HUMAN_REJECTED_NO_PUBLICATION_EXPECTED'
    if decision!='editorially_accepted_not_published':return 'UNEXPECTED_EDITORIAL_DECISION'
    if pub is not None:
        if pub.get('status')=='PUBLIC_PUBLISHED_CONFIRMED':
            if pub.get('channel_id')==EXPECTED_CHANNEL and isinstance(pub.get('message_id'),int):
                return 'PUBLIC_PUBLISHED_CONFIRMED'
            return 'PUBLIC_ACK_DESTINATION_MISMATCH'
        if pub.get('status')=='PUBLIC_SEND_UNCERTAIN_NO_RETRY':
            return 'PUBLIC_SEND_UNCERTAIN_NO_RETRY_DO_NOT_RESEND'
        return 'PUBLIC_LEDGER_UNEXPECTED_STATUS'
    if not activation or activation.get('status')!='ACTIVE':
        return 'PUBLICATION_NOT_ACTIVE'
    if not receipt.get('telegram_photo_file_id'):return 'PRIVATE_PHOTO_FILE_ID_MISSING'
    return 'APPROVED_AWAITING_AUTOMATIC_PUBLICATION'
def report():
    if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
    key,receipt=find_card()
    decision=safe_json(OP/'news_rg_editorial_decisions_v1'/(key+'.json'))
    pub=safe_json(OP/'news_rg_publication_receipts_v1'/(key+'.json'))
    activation=safe_json(OP/'news_rg_publication_activation_v1.json')
    if decision and (decision.get('draft_id')!=key or
          decision.get('telegram_message_id')!=TARGET_MESSAGE or
          decision.get('public_publication')!='OFF'):
        raise RuntimeError('EDITORIAL_DECISION_MISMATCH')
    if pub and pub.get('draft_id')!=key:raise RuntimeError('PUBLIC_RECEIPT_DRAFT_MISMATCH')
    tick=BASE/'rg_news_dsm_tick.sh'
    content=tick.read_text('utf8') if tick.is_file() and not tick.is_symlink() and tick.stat().st_size<50000 else ''
    decision_at=decision.get('timestamp') if decision else None
    published_at=pub.get('published_at') if pub else None
    launch=marker(OP/'news_rg_publication_last_launch')
    stage=marker(OP/'news_rg_last_launch_utc')
    code=classify(decision,pub,receipt,activation)
    return {
      'schema':'NEWS_RG_CARD_8054_UNATTENDED_AUDIT_V1',
      'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'read_only':True,'network_requests':0,'telegram_calls':0,'publications_triggered':0,
      'private_card_id':TARGET_MESSAGE,
      'draft_id':key,
      'decision':decision.get('decision') if decision else 'NOT_RECORDED',
      'decision_age_minutes':age(decision_at),
      'publication_status':pub.get('status') if pub else 'NO_PUBLIC_RECEIPT',
      'public_channel_id':pub.get('channel_id') if pub else None,
      'public_message_id':pub.get('message_id') if pub and isinstance(pub.get('message_id'),int) else None,
      'publication_age_minutes':age(published_at),
      'approved_to_published_minutes':round((published_at-decision_at)/60,2)
          if isinstance(published_at,int) and isinstance(decision_at,int) and published_at>=decision_at else None,
      'publisher_activation_status':activation.get('status') if activation else 'MISSING',
      'dsm_publication_hook_present':content.count('# NEWS_RG_APPROVED_PUBLICATION_CUTOVER_V1')==1 and
          content.count('news_rg_publication_schedule_v1.py')==1,
      'dsm_publication_launch_after_decision':bool(launch and isinstance(decision_at,int) and launch>=decision_at),
      'last_publication_schedule_launch_age_minutes':age(launch),
      'last_source_ai_launch_age_minutes':age(stage),
      'last_publication_autorun_log':log_last(OP/'news_rg_publication_autorun.log'),
      'verdict':code,
      'unattended_proof_note':'The schedule marker itself does not distinguish a DSM invocation from a manually invoked tick.'
    }
def selftest():
    assert classify(None,None,{},None)=='CALLBACK_DECISION_NOT_RECORDED'
    rejected={'decision':'editorially_rejected'}
    assert classify(rejected,None,{},None)=='HUMAN_REJECTED_NO_PUBLICATION_EXPECTED'
    approved={'decision':'editorially_accepted_not_published'}
    assert classify(approved,None,{'telegram_photo_file_id':'abc'}, {'status':'ACTIVE'})=='APPROVED_AWAITING_AUTOMATIC_PUBLICATION'
    assert classify(approved,{'status':'PUBLIC_SEND_UNCERTAIN_NO_RETRY'},{},{})=='PUBLIC_SEND_UNCERTAIN_NO_RETRY_DO_NOT_RESEND'
    assert classify(approved,{'status':'PUBLIC_PUBLISHED_CONFIRMED','channel_id':EXPECTED_CHANNEL,'message_id':7876},{},{})=='PUBLIC_PUBLISHED_CONFIRMED'
    print('NEWS_RG_CARD_8054_UNATTENDED_AUDIT_SELFTEST_PASS')
if __name__=='__main__':
    try:
        if sys.argv[1:]==['selftest']:selftest()
        elif sys.argv[1:]==['inspect']:print(json.dumps(report(),ensure_ascii=False,sort_keys=True,indent=2))
        else:raise RuntimeError('EXPECTED_SELFTEST_OR_INSPECT')
    except Exception as exc:
        print(json.dumps({'status':'SAFE_STOP','reason':str(exc)[:120],'publications_triggered':0}))
        sys.exit(2)
