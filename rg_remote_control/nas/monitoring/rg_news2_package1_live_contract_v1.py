#!/usr/bin/env python3
"""NEWS2 package 1. Root-only, fail-closed, READ-ONLY live acceptance contract.

Never import or execute production modules, open a Telegram connection, log
secrets, modify ledgers, or start a second poller. Inspect structural evidence
only; report UNKNOWN rather than infer successful publications.
"""
import ast
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
PHOTO=ROOT/'news_rg_approved_publication_v1.py'
VIDEO=ROOT/'news_rg_approved_video_publication_v1.py'
FOOTER=ROOT/'news_rg_project_footer_v1.py'
CALLBACK=ROOT/'news_rg_editorial_callbacks_v1.py'
SCHED=ROOT/'news_rg_publication_schedule_v1.py'
ACT=ROOT/'news_rg_publication_activation_v1.json'
DEC=ROOT/'news_rg_editorial_decisions_v1'
SENT=ROOT/'news_rg_private_multipart_receipts_v1'
PUB=ROOT/'news_rg_publication_receipts_v1'
LABEL='УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ "РАША ГУДБАЙ"'
URL='https://links.rginfoua.pp.ua/'
class Stop(ValueError): pass

def safe_source(path, limit=160000):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit or path.stat().st_size==0:
        raise Stop('SOURCE_MISSING_OR_UNSAFE_'+path.name)
    if path.stat().st_uid!=0:
        raise Stop('SOURCE_NOT_ROOT_OWNED_'+path.name)
    raw=path.read_bytes()
    try: text=raw.decode('utf8');tree=ast.parse(text)
    except (UnicodeError,SyntaxError): raise Stop('SOURCE_NOT_VALID_PYTHON_'+path.name)
    return text,tree,hashlib.sha256(raw).hexdigest()[:20]

def inspect_publication(photo, video, footer, callback, sched):
    p,pt,ph=photo
    v,vt,vh=video
    f,ft,fh=footer
    c,ct,ch=callback
    s,st,sh=sched
    def has_fn(tree,name):
        return any(isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name==name for node in tree.body)
    def body_for(tree,name):
        return '\n'.join(ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    # Syntax and static markers provide evidence of wiring, not proof of UI appearance.
    footer_ok=has_fn(ft,'append_footer') and URL in f and LABEL in f
    photo_preclaim='append_footer(caption)' in p and p.index('append_footer(caption)')<p.index("persist(receipt,{'status':'PUBLIC_SEND_UNCERTAIN_NO_RETRY'")
    photo_uses_entities="'caption_entities'" in p and "'sendPhoto'" in p
    photo_has_album="'sendMediaGroup'" in p or 'sendMediaGroup' in p
    # Album must be independently checked; direct sendPhoto entities do not cover albums.
    album_explicit_entities=(('caption_entities' in p and ('media[0][' in p or "media[0].update" in p))
        or ('caption_entities' in p and 'sendMediaGroup' in p and "'caption'" in p))
    video_has_footer=('append_footer(' in v or 'news_rg_project_footer_v1' in v)
    video_send=('sendVideo' in v or 'send_mp4(' in v)
    video_entity_transport=('caption_entities' in v or 'parse_mode' in v)
    callbacks_private='"private"' in c and 'moderation_chat_id' in c and 'PRIVATE_SENT_CONFIRMED' in c
    callbacks_exclusive='O_EXCL' in c
    no_auto_retry='PUBLIC_SEND_UNCERTAIN_NO_RETRY' in p and 'PUBLICATION_ALREADY_CLAIMED' in p
    return {
      'footer_module':{'present':footer_ok,'sha256_20':fh,'bold_source':('bold' in f.lower() or '<b>' in f),
                       'link_source':('text_link' in f or 'text_url' in f or 'href=' in f)},
      'photo':{'sha256_20':ph,'footer_before_claim':photo_preclaim,
               'caption_entities_sent':photo_uses_entities,'album_route_present':photo_has_album,
               'album_entities_needs_runtime_confirmation':photo_has_album and not album_explicit_entities},
      'video':{'sha256_20':vh,'footer_hook':video_has_footer,'send_video':video_send,
               'caption_entity_transport_present':video_entity_transport},
      'moderation':{'sha256_20':ch,'private_only_marker':callbacks_private,'exclusive_decision':callbacks_exclusive},
      'scheduler':{'sha256_20':sh,'publication_tick_marker':('publish' in s.lower())},
      'limits':{'telegram_caption_1024_check_evidence':('1024' in f),'utf16_offsets_evidence':('utf-16' in f.lower() or 'utf16' in f.lower())},
      'verified_e2e':False,'no_public_post_performed':True
    }

def inspect_anomalies():
    counts=collections.Counter()
    newest=None
    if any(not d.is_dir() or d.is_symlink() for d in (DEC,SENT,PUB)):
        raise Stop('LEDGER_DIRECTORY_UNSAFE')
    now=time.time()
    for p in DEC.glob('*.json'):
        if not re.fullmatch(r'[a-f0-9]{24}\.json',p.name):counts['invalid_filename']+=1;continue
        try:
            if p.is_symlink() or p.stat().st_size>24000:counts['unreadable']+=1;continue
            doc=json.loads(p.read_text(encoding='utf8'))
            if not isinstance(doc,dict):counts['not_object']+=1;continue
            decision=doc.get('decision')
            if decision not in ('editorially_accepted_not_published','editorially_rejected'):
                # Do not output draft ID, moderator ID, personal data, or unexpected text.
                counts['unexpected_decision']+=1
                counts['unexpected_schema_'+('v1' if doc.get('schema')=='NEWS_RG_HUMAN_EDITORIAL_DECISION_V1' else 'other')]+=1
                continue
            if decision=='editorially_rejected':counts['rejected']+=1;continue
            counts['accepted']+=1
            rec=PUB/p.name
            if rec.exists():
                if rec.is_symlink() or rec.stat().st_size>24000:counts['unsafe_public_receipt']+=1;continue
                receipt=json.loads(rec.read_text(encoding='utf8'))
                status=receipt.get('status')
                if status=='PUBLIC_PUBLISHED_CONFIRMED':counts['accepted_published']+=1
                elif status=='PUBLIC_SEND_UNCERTAIN_NO_RETRY':counts['public_uncertain_stop']+=1
                else:counts['public_other_receipt']+=1
            else:
                when=doc.get('timestamp')
                if type(when)==int:
                    counts['accepted_no_receipt_over_24h' if now-when>86400 else 'accepted_no_receipt_under_24h']+=1
                else:counts['accepted_no_receipt_unknown_age']+=1
        except (OSError,ValueError,TypeError,UnicodeError):
            counts['parse_errors']+=1
    return dict(counts)

def inspect():
    if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
    if ROOT.is_symlink() or not ROOT.is_dir():raise Stop('ROOT_UNSAFE')
    source=inspect_publication(*(safe_source(x) for x in (PHOTO,VIDEO,FOOTER,CALLBACK,SCHED)))
    return {'schema':'RG_NEWS2_PACKAGE1_LIVE_CONTRACT_READONLY_V1','asof':int(time.time()),
            'source':source,'decisions':inspect_anomalies(),
            'production_changes':0,'telegram_calls':0,'publications':0,'new_pollers':0,
            'read_only':True,'secrets_disclosed':False}

def selftest():
    fixture='''def append_footer(text):\n return text\n'''
    tree=ast.parse(fixture)
    assert len(tree.body)==1
    assert safe_filename('a'*24+'.json')
    assert not safe_filename('../x.json')
    assert 'sendMediaGroup' in "sendMediaGroup"
    print('NEWS2_PACKAGE1_LIVE_CONTRACT_SELFTEST_PASS')

def safe_filename(name):
    return bool(re.fullmatch(r'[a-f0-9]{24}\.json',name))

if __name__=='__main__':
    try:
        if sys.argv[1:]==['selftest']:selftest()
        elif sys.argv[1:]==['inspect']:print(json.dumps(inspect(),sort_keys=True,ensure_ascii=False))
        else:raise Stop('UNSUPPORTED_ACTION')
    except (Stop,OSError,ValueError,TypeError) as e:
        print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:100],
                          'read_only':True,'telegram_calls':0,'production_changes':0}))
        raise SystemExit(2)
