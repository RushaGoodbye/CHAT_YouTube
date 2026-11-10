#!/usr/bin/env python3
"""RG Shorts V3: private review, human decision, public at-most-once, no scheduler/poller.

Existing pinned NEWS RG callback module calls process_callback(update,cfg).
No direct publication from a callback. No automatic retry on uncertain delivery.
"""
import argparse
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import time
import urllib.request
import urllib.parse
import uuid

O=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
sys.path.insert(0,str(O))
sys.path.insert(0,str(O.parent))
import rg_shorts_no_repeat_v1 as inv

RECEIPTS=O/'rg_shorts_v3_receipts'
LOCK=O/'rg_shorts_v3.lock'
MAX=44*1024*1024
CALLBACK=re.compile(r'^rgs3:(accept|reject):([a-f0-9]{24})$')
FOOTER='УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ «РАША ГУДБАЙ»'
LINKS='https://links.rginfoua.pp.ua/'
CHANNEL='https://t.me/RussiaGoodbyeUA'

def stop(s):raise RuntimeError(s)
def out(s,**kwargs):print(json.dumps(dict(status=s,**kwargs),ensure_ascii=False,sort_keys=True))
def safe_file(p):
    if p.is_symlink() or not p.is_file() or p.stat().st_size>20000:stop('RECEIPT_INVALID')
    return json.loads(p.read_text('utf-8'))
def write(p,v,exclusive=False):
    if p.is_symlink():stop('SYMLINK_REFUSED')
    if exclusive:
        with os.fdopen(os.open(str(p),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w',encoding='utf8') as f:
            json.dump(v,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
        return
    tmp=p.with_name('.'+p.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with os.fdopen(os.open(str(tmp),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w',encoding='utf8') as f:
            json.dump(v,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
        os.replace(tmp,p)
    finally:
        if tmp.exists():tmp.unlink()
def lock():
    fd=os.open(str(LOCK),os.O_CREAT|os.O_RDWR,0o600)
    fcntl.flock(fd,fcntl.LOCK_EX)
    return fd
def config():
    import rg_moderation
    import news_rg_multipart
    cfg=rg_moderation.config()
    chat=cfg.get('moderation_chat_id')
    moderators={int(v) for v in cfg.get('moderators',[])}
    if type(chat)!=int or chat<=0 or not moderators:stop('MODERATION_CONFIG_UNVERIFIED')
    return cfg,chat,moderators,news_rg_multipart.token()
def compact_title(name):
    name=re.sub(r'[_-]+',' ',name).strip()
    if not name:name='ВІДЕОФРАГМЕНТ'
    name=name[:90].upper()
    # Lowercase the entire word 'росія' and derivatives despite uppercase title.
    name=re.sub(r'(?iu)рос[іи][яїи][\wіїєґ]*',lambda m:m.group(0).lower(),name)
    return name

def caption(path):
    label=html.escape(compact_title(path.stem))
    return f'<b>🎬 {label}</b>\n💬 Що думаєте про побачене? Напишіть у коментарях.'

def link_buttons():
    return [
        [{'text':'🔔 ПІДПИСАТИСЯ НА «РАША ГУДБАЙ»','url':CHANNEL,'style':'primary'}],
        [{'text':'🟨 УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ','url':LINKS}]
    ]

def review_buttons(draft):
    return {'inline_keyboard':[
        [{'text':'✅ Схвалити (без автопублікації)','callback_data':'rgs3:accept:'+draft,'style':'success'},
         {'text':'❌ Відхилити','callback_data':'rgs3:reject:'+draft,'style':'danger'}],
        *link_buttons()]}

def format_review_caption(text):
    return '⚠️ ПРИВАТНА МОДЕРАЦІЯ SHORTS\n\n'+text

def grounded_ai_caption(path):
    """Only create model-specific descriptions from an actual SRT/TXT transcript.
    The optional local model service is configured by RG_SHORTS_V3_AI_URL.
    If unavailable, return None and use an explicitly generic, reviewable caption.
    """
    import urllib.parse
    import ipaddress
    transcript=None
    for suffix in ('.srt','.txt'):
        p=path.with_suffix(suffix)
        if p.is_file() and not p.is_symlink() and p.stat().st_size<=160000:
            transcript=p.read_text('utf8',errors='replace')[:25000]
            break
    endpoint=os.environ.get('RG_SHORTS_V3_AI_URL','').strip()
    if not transcript or not endpoint:return None
    uri=urllib.parse.urlsplit(endpoint)
    try: addr=ipaddress.ip_address(uri.hostname or '')
    except ValueError: return None
    if (uri.scheme!='http' or not addr.is_private or uri.path!='/v1/chat/completions'
            or uri.username or uri.password or uri.query):return None
    prompt=('На основі лише субтитрів напиши один інтригуючий заголовок і '
            'одне або два короткі речення українською, разом до 350 символів. '
            'Не вигадуй жодних фактів, не перебільшуй; росія та всі її похідні '
            'завжди з малої літери. Лише чистий текст без посилань чи хештегів.\n'
            'СУБТИТРИ:\n'+transcript)
    req=urllib.request.Request(endpoint,
        data=json.dumps({'model':os.environ.get('RG_SHORTS_V3_AI_MODEL','gemma-4-12b'),
                         'messages':[{'role':'user','content':prompt}],
                         'temperature':0.2,'max_tokens':350}).encode('utf8'),
        headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=45) as response:
            result=json.loads(response.read(100000))
        candidate=result['choices'][0]['message']['content'].strip()
        if not 35<=len(candidate)<=350:return None
        if any(char in candidate for char in ('ы','ъ','э','ё','Ы','Ъ','Э','Ё')):return None
        if 'http://' in candidate or 'https://' in candidate:return None
        candidate=re.sub(r'(?i)рос[іи][яїи][\wіїєґ]*',lambda m:m.group(0).lower(),candidate)
        return candidate
    except (OSError,ValueError,KeyError,IndexError,TypeError):
        return None

def multipart(chat,video,caption_text,buttons=None):
    boundary='rgs'+uuid.uuid4().hex
    fields=[('chat_id',str(chat)),('caption',caption_text),
            ('parse_mode','HTML'),('supports_streaming','true')]
    if buttons is not None:fields.append(('reply_markup',json.dumps(buttons,ensure_ascii=False)))
    chunks=[]
    for key,value in fields:
        chunks.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+
                        '"\r\n\r\n'+value+'\r\n').encode('utf8'))
    chunks.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="video"; filename="short.mp4"\r\n'
                   'Content-Type: video/mp4\r\n\r\n').encode()+video+b'\r\n')
    chunks.append(('--'+boundary+'--\r\n').encode())
    return b''.join(chunks),boundary
def send(token,chat,video,text,buttons=None):
    body,bound=multipart(chat,video,text,buttons)
    req=urllib.request.Request('https://api.telegram.org/bot'+token+'/sendVideo',
        data=body,headers={'Content-Type':'multipart/form-data; boundary='+bound})
    with urllib.request.urlopen(req,timeout=120) as resp:
        ack=json.loads(resp.read(100000))
    msg=ack.get('result') if ack.get('ok') is True else None
    if not isinstance(msg,dict) or type(msg.get('message_id'))!=int or int((msg.get('chat') or {}).get('id',0))!=chat:
        stop('TELEGRAM_ACK_INVALID')
    return msg['message_id']
def choose(cn):
    candidates=cn.execute("SELECT sha256,example_path,size_bytes FROM files "
                          "WHERE state='AVAILABLE' AND size_bytes BETWEEN 1024 AND ?",(MAX,)).fetchall()
    if not candidates:stop('NO_ELIGIBLE_SHORTS')
    start=secrets.randbelow(len(candidates))
    for k in range(len(candidates)):
        r=candidates[(start+k)%len(candidates)];p=Path(r['example_path'])
        if p.is_symlink() or not p.is_file() or p.suffix.lower()!='.mp4':continue
        if not p.resolve().is_relative_to(inv.SOURCE.resolve()):continue
        st=p.stat()
        if st.st_size!=r['size_bytes'] or st.st_size>MAX:continue
        data=p.read_bytes()
        if hashlib.sha256(data).hexdigest()==r['sha256'] and data[4:8]==b'ftyp':
            return r,p,data
    stop('VERIFIED_SHORTS_NOT_FOUND')
def ready():
    if os.geteuid()!=0:stop('SUDO_REQUIRED')
    if RECEIPTS.is_symlink():stop('RECEIPT_FOLDER_SYMLINK')
    RECEIPTS.mkdir(mode=0o700,exist_ok=True);os.chmod(RECEIPTS,0o700)
    if not inv.DB.is_file() or inv.DB.is_symlink():stop('INVENTORY_NOT_FOUND')
def send_private():
    ready()
    lk=lock()
    try:
        cfg,chat,moderators,token=config()
        cn=inv.db_open()
        try:
            row,path,data=choose(cn)
            draft=secrets.token_hex(12);sha=row['sha256']
            proposed=caption(path)
            ai_text=grounded_ai_caption(path)
            if ai_text:
                # AI is draft-only; retain the exact compact two-line layout.
                ai_title=compact_title(ai_text.splitlines()[0])
                proposed='<b>🎬 '+html.escape(ai_title)+'</b>\n💬 Що думаєте про побачене? Напишіть у коментарях.'
            source_mode='TRANSCRIPT_AI_DRAFT_HUMAN_REVIEW' if ai_text else 'FILENAME_GENERIC_HUMAN_REVIEW'
            cards=review_buttons(draft)
            # Atomic SHA claim BEFORE network; a crash cannot cause reuse.
            cn.execute('BEGIN IMMEDIATE')
            n=cn.execute("UPDATE files SET state='RESERVED',reserved_at=?,note=? WHERE sha256=? AND state='AVAILABLE'",
                         (int(time.time()),'RG_SHORTS_V3_PRIVATE_REVIEW:'+draft,sha)).rowcount
            if n!=1:cn.rollback();stop('RESERVE_RACE')
            cn.execute('INSERT INTO events(sha256,event,at,details) VALUES(?,?,?,?)',(sha,'V3_PRIVATE_CLAIM',int(time.time()),draft))
            cn.commit()
            p=RECEIPTS/(draft+'.json')
            rec=dict(schema='RG_SHORTS_V3',draft_id=draft,sha256=sha,source=str(path),
                     caption=proposed,caption_source=source_mode,state='PRIVATE_SEND_UNCERTAIN_NO_RETRY',
                     claimed_at=int(time.time()),private_chat_id=chat,publications=0)
            write(p,rec,exclusive=True)
            try:
                mid=send(token,chat,data,format_review_caption(proposed),cards)
                rec.update(state='PRIVATE_SENT_CONFIRMED',private_message_id=mid)
                write(p,rec)
                out('PRIVATE_SENT_CONFIRMED',draft_id=draft,sha256=sha,message_id=mid,publications=0)
            except Exception as exc:
                rec.update(error_class=type(exc).__name__)
                write(p,rec)
                out('PRIVATE_SEND_UNCERTAIN_NO_RETRY',draft_id=draft,sha256=sha,
                    error_class=type(exc).__name__,publications=0)
        finally:cn.close()
    finally:os.close(lk)
def process_callback(update,cfg):
    q=(update or {}).get('callback_query') or {}
    m=CALLBACK.fullmatch(str(q.get('data','')))
    if not m:return None
    action,draft=m.groups()
    lk=lock()
    try:
        p=RECEIPTS/(draft+'.json')
        rec=safe_file(p)
        if rec.get('schema')!='RG_SHORTS_V3' or rec.get('draft_id')!=draft or rec.get('state')!='PRIVATE_SENT_CONFIRMED':
            return {'status':'SHORTS_NOT_ELIGIBLE'}
        actor=int((q.get('from') or {}).get('id',0))
        msg=q.get('message') or {}
        chat=msg.get('chat') or {}
        moderators={int(i) for i in cfg.get('moderators',[])}
        expected=int(cfg.get('moderation_chat_id',0))
        if actor not in moderators or actor<=0 or expected<=0 or int(chat.get('id',0))!=expected or chat.get('type')!='private':
            return {'status':'SHORTS_MODERATOR_UNVERIFIED'}
        if msg.get('message_id')!=rec.get('private_message_id') or rec.get('private_chat_id')!=expected:
            return {'status':'SHORTS_MESSAGE_MISMATCH'}
        if action=='accept':
            rec.update(state='APPROVED_AWAITING_MANUAL_PUBLICATION',approved_at=int(time.time()),moderator_id=actor)
        else:
            rec.update(state='REJECTED_NO_RESEND',rejected_at=int(time.time()),moderator_id=actor)
        write(p,rec)
        return {'status':rec['state'],'public_publication':'OFF','draft_id':draft}
    except (OSError,ValueError,TypeError,RuntimeError,KeyError):
        return {'status':'SHORTS_CALLBACK_SAFE_STOP'}
    finally:os.close(lk)
def publish_one():
    ready()
    lk=lock()
    try:
        # Reuse the exact activation / channel admin verification of the live publisher.
        import news_rg_approved_publication_v1 as pub
        pub_lock=os.open(str(pub.LCK),os.O_CREAT|os.O_RDWR,0o600)
        try:
            fcntl.flock(pub_lock,fcntl.LOCK_EX)
            act=pub.gate()
            rows=[]
            for p in RECEIPTS.glob('*.json'):
                if p.is_symlink():stop('UNSAFE_RECEIPT')
                r=safe_file(p)
                if r.get('state')=='PUBLIC_SEND_UNCERTAIN_NO_RETRY':stop('PREVIOUS_SHORTS_PUBLIC_SEND_UNCERTAIN')
                if r.get('state')=='APPROVED_AWAITING_MANUAL_PUBLICATION':rows.append((r.get('approved_at',0),p,r))
            if not rows:
                out('NO_APPROVED_SHORTS',publications=0);return
            _,p,r=sorted(rows,key=lambda x:x[0])[0]
            if int(time.time())-r['approved_at']>86400:stop('APPROVAL_EXPIRED')
            cfg=pub.module();token=pub.credentials()
            dest=pub.verify_channel(cfg,token)
            if dest['chat_id']!=act['chat_id'] or dest['bot_id']!=act['bot_id']:stop('PUBLIC_CHANNEL_PIN_MISMATCH')
            source=Path(r['source']);sha=r['sha256']
            if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(inv.SOURCE.resolve()):stop('SOURCE_CHANGED')
            video=source.read_bytes()
            if len(video)>MAX or video[4:8]!=b'ftyp' or hashlib.sha256(video).hexdigest()!=sha:stop('VIDEO_HASH_MISMATCH')
            # Durable claim BEFORE network; every uncertain send stays blocked.
            r.update(state='PUBLIC_SEND_UNCERTAIN_NO_RETRY',public_claimed_at=int(time.time()))
            write(p,r)
            try:
                mid=send(token,act['chat_id'],video,r['caption'],{'inline_keyboard':link_buttons()})
                r.update(state='PUBLIC_PUBLISHED_CONFIRMED',public_message_id=mid,published_at=int(time.time()),publications=1)
                write(p,r)
                cn=inv.db_open()
                try:
                    cn.execute('BEGIN IMMEDIATE')
                    cn.execute("UPDATE files SET state='PUBLISHED',published_at=?,telegram_message_id=?,note=? "
                               "WHERE sha256=? AND state='RESERVED'",
                               (int(time.time()),mid,'RG_SHORTS_V3_PUBLIC:'+r['draft_id'],sha))
                    cn.execute('INSERT INTO events(sha256,event,at,details) VALUES(?,?,?,?)',
                               (sha,'V3_PUBLIC_CONFIRMED',int(time.time()),str(mid)))
                    cn.commit()
                finally:cn.close()
                out('PUBLIC_PUBLISHED_CONFIRMED',draft_id=r['draft_id'],sha256=sha,message_id=mid,publications=1)
            except Exception as exc:
                out('PUBLIC_SEND_UNCERTAIN_NO_RETRY',draft_id=r['draft_id'],
                    error_class=type(exc).__name__,publications=0)
        finally:os.close(pub_lock)
    finally:os.close(lk)
def status():
    ready()
    c=inv.db_open()
    try:
        states={r['state']:r['n'] for r in c.execute('SELECT state,COUNT(*) n FROM files GROUP BY state')}
        queue={}
        for p in RECEIPTS.glob('*.json'):
            r=safe_file(p);s=r.get('state','UNKNOWN');queue[s]=queue.get(s,0)+1
        out('RG_SHORTS_V3_INSTALLED',inventory=states,review=queue,scheduler='OFF',publications_triggered=0)
    finally:c.close()
def refresh_private_card(draft):
    """Edit the already delivered private message, never upload the same video again."""
    ready()
    if not re.fullmatch(r'[a-f0-9]{24}',draft):stop('BAD_DRAFT_ID')
    lk=lock()
    try:
        p=RECEIPTS/(draft+'.json')
        r=safe_file(p)
        if r.get('state')!='PRIVATE_SENT_CONFIRMED' or r.get('schema')!='RG_SHORTS_V3':
            stop('PRIVATE_CARD_NOT_EDITABLE')
        cfg,chat,moderators,token=config()
        if r.get('private_chat_id')!=chat or type(r.get('private_message_id'))!=int:
            stop('PRIVATE_MESSAGE_ID_INVALID')
        source=Path(r['source'])
        if not source.is_file() or source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest()!=r['sha256']:
            stop('SOURCE_CHANGED')
        updated=caption(source)
        body=urllib.parse.urlencode({
            'chat_id':str(chat),'message_id':r['private_message_id'],
            'caption':format_review_caption(updated),'parse_mode':'HTML',
            'reply_markup':json.dumps(review_buttons(draft),ensure_ascii=False)
        }).encode('utf8')
        req=urllib.request.Request('https://api.telegram.org/bot'+token+'/editMessageCaption',
                                   data=body,headers={'Content-Type':'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(req,timeout=30) as resp:
            ack=json.loads(resp.read(80000))
        msg=ack.get('result') if ack.get('ok') is True else None
        if not isinstance(msg,dict) or msg.get('message_id')!=r['private_message_id'] or int((msg.get('chat') or {}).get('id',0))!=chat:
            stop('EDIT_ACK_NOT_CONFIRMED')
        r['caption']=updated
        r['caption_source']='FORMATTING_UPDATE_FROM_FILENAME'
        r['format_revision']='V3_COMPACT_BUTTONS'
        r['last_edit_at']=int(time.time())
        write(p,r)
        out('PRIVATE_CARD_UPDATED_IN_PLACE',draft_id=draft,message_id=r['private_message_id'],
            same_video=True,publications=0)
    finally:os.close(lk)

def selftest():
    x=caption(Path('Росія і РОСІЯНИН.mp4'))
    assert 'Росія' not in x and 'РОСІЯНИН' not in x
    assert 'youtube.com' not in x.lower()
    assert 'Короткий відеофрагмент' not in x
    assert x.startswith('<b>🎬 ') and '\n💬 ' in x
    assert link_buttons()[0][0]['style']=='primary'
    assert link_buttons()[1][0]['url']==LINKS
    assert CALLBACK.fullmatch('rgs3:accept:'+'a'*24)
    assert CALLBACK.fullmatch('rgs3:reject:'+'a'*24)
    assert not CALLBACK.fullmatch('ne1:accept:'+'a'*24)
    out('RG_SHORTS_V3_SELFTEST_PASS',publications=0)
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('action',choices=['selftest','status','send-one-private','publish-one','refresh-private-card'])
    ap.add_argument('--draft-id',default='')
    args=ap.parse_args()
    if args.action=='selftest':selftest()
    elif args.action=='status':status()
    elif args.action=='send-one-private':send_private()
    elif args.action=='refresh-private-card':refresh_private_card(args.draft_id)
    else:publish_one()
if __name__=='__main__':
    try:main()
    except Exception as exc:
        out('SAFE_STOP',error_class=type(exc).__name__,reason=str(exc)[:100] if isinstance(exc,RuntimeError) else 'CHECK_LOCAL_LOG',publications=0)
        sys.exit(2)
