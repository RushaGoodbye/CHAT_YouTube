#!/usr/bin/env python3
"""NEWS2 next-packet live contract checker; NO publishing or mutation.

This read-only program is a release gate, NOT a Telegram publisher.
It checks live module structure, caption entities, approved-media evidence,
duplicate protections and watermark provenance. NEVER leaks credentials,
draft IDs or message text. Requires root for protected files.
"""
import ast
from collections import Counter
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time

ROOT=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
FILES={
  'photo':'news_rg_approved_publication_v1.py',
  'video':'news_rg_approved_video_publication_v1.py',
  'footer':'news_rg_project_footer_v1.py',
  'render':'news_rg_nas_video_pipeline_v1.py',
  'scheduler':'news_rg_publication_schedule_v1.py',
}
WATERMARK=ROOT/'news_rg_nas_watermarked_v1'
PUB=ROOT/'news_rg_publication_receipts_v1'
DEC=ROOT/'news_rg_editorial_decisions_v1'
PRIVATE=ROOT/'news_rg_private_multipart_receipts_v1'
STAGED=ROOT/'news_rg_private_review_staging'
HEX=re.compile(r'[0-9a-f]{24}\.json\Z')
class Block(ValueError):pass

def safe_source(p):
    st=p.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_size>220000 or st.st_size==0:
        raise Block('UNSAFE_SOURCE_'+p.name)
    body=p.read_text(encoding='utf-8')
    return body,ast.parse(body)

def safe_record(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>35000:
        raise Block('UNSAFE_RECORD')
    x=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(x,dict):raise Block('RECORD_NOT_OBJECT')
    return x

def tally(root):
    if root.is_symlink() or not root.is_dir():raise Block('UNSAFE_LEDGER')
    return len([x for x in root.glob('*.json') if HEX.fullmatch(x.name) and not x.is_symlink()])

def analyze_content(src):
    # First-party sources are NOT imported here; no network-capable code runs.
    lines=src.splitlines()
    return {
        'has_footer_hook': 'append_footer(' in src,
        'has_footer_entities': 'caption_entities' in src,
        'uses_telegram_entities': any(w in src for w in ("'text_link'","'text_url'","'bold'","\"text_link\"","\"bold\"")),
        'has_html_parse_mode': 'parse_mode' in src,
        'has_idempotent_claim': 'O_EXCL' in src,
        'has_uncertain_no_retry': 'PUBLIC_SEND_UNCERTAIN_NO_RETRY' in src,
        'has_exclusive_lock': 'fcntl.flock' in src,
        'uses_channel_identity_pin': 'PINNED_PUBLICATION_IDENTITY_CHANGED' in src or 'CHANNEL_IDENTITY_CHANGED' in src,
        'has_24h_guard': '24*3600' in src or '86400' in src or '24 * 3600' in src,
        'has_caption_limits': '1024' in src or '900' in src,
        'has_telegram_calls': 'sendPhoto' in src or 'sendVideo' in src,
    }

def watermark_candidates():
    # Small allowlisted directories only; never return image contents.
    dirs=[ROOT,ROOT/'assets',ROOT/'branding',ROOT/'watermark',
          ROOT/'watermarks',ROOT.parent/'assets']
    files=[]
    for folder in dirs:
        if folder.is_symlink() or not folder.is_dir():continue
        try:items=list(folder.glob('*.png'))[:50]
        except OSError:continue
        for p in items:
            try:
                if p.is_symlink() or not p.is_file() or p.stat().st_size>15000000:continue
                with p.open('rb') as file:
                    header=file.read(24)
                    if header[:8]!=b'\x89PNG\r\n\x1a\n':continue
                    width=int.from_bytes(header[16:20],'big')
                    height=int.from_bytes(header[20:24],'big')
                    if not 1<=width<=8192 or not 1<=height<=8192:continue
                    file.seek(0)
                    sha=hashlib.sha256()
                    for block in iter(lambda:file.read(1048576),b''):sha.update(block)
                files.append({'relative_dir':str(folder.relative_to(ROOT.parent)),
                              'filename':p.name[:90],'sha256':sha.hexdigest(),
                              'width':width,'height':height})
            except (OSError,ValueError):continue
    return files[:20]

def inspect():
    if os.geteuid()!=0:raise Block('ROOT_REQUIRED')
    if ROOT.is_symlink() or not ROOT.is_dir():raise Block('OPERATOR_UNSAFE')
    raw={}
    modules={}
    for k,name in FILES.items():
        try:
            s,tree=safe_source(ROOT/name)
            raw[k]=s
            modules[k]={'present':True,'syntax_ok':True,
                        'sha256_prefix':hashlib.sha256(s.encode('utf8')).hexdigest()[:20],
                        'features':analyze_content(s)}
        except (FileNotFoundError,UnicodeError,SyntaxError,Block,OSError):
            modules[k]={'present':False,'syntax_ok':False}
            raw[k]=''
    photo=modules['photo']['features'] if modules['photo']['present'] else {}
    video=modules['video']['features'] if modules['video']['present'] else {}
    footer=raw['footer']
    renderer=raw['render']
    scheduler=raw['scheduler']
    requirements={
      'photo_durable_claim_and_lock':all(photo.get(k) for k in ('has_idempotent_claim','has_uncertain_no_retry','has_exclusive_lock','uses_channel_identity_pin','has_24h_guard')),
      'photo_footer_before_send':bool(re.search(r'append_footer\s*\(\s*caption\s*\)',raw['photo'])) and bool(re.search(r'caption_entities',raw['photo'])),
      'album_caption_entities':('sendMediaGroup' not in raw['photo'] or 'caption_entities' in raw['photo']),
      'video_durable_receipt':all(video.get(k) for k in ('has_uncertain_no_retry','has_exclusive_lock','uses_channel_identity_pin','has_24h_guard')),
      'video_footer_reference':('news_rg_project_footer_v1' in raw['video'] or 'append_footer(' in raw['video']),
      'video_caption_format':('caption_entities' in raw['video'] or 'parse_mode' in raw['video']),
      'footer_target_url':('https://links.rginfoua.pp.ua/' in footer),
      'footer_bold_text_link':('bold' in footer and ('text_link' in footer or 'text_url' in footer or 'href=' in footer)),
      'footer_callable':('def append_footer(' in footer),
      'scheduler_approval_route':('publish-one' in scheduler and 'news_rg_approved_publication_v1.py' in scheduler),
      'renderer_requires_watermark':('drawtext' in renderer or 'overlay=' in renderer),
      'renderer_receipt_has_sha256':("'sha256'" in renderer or '"sha256"' in renderer),
    }
    counters={'public_receipts':0,'public_confirmed':0,'public_uncertain':0,
              'private_confirmed':0,'accepted':0,'rejected':0,
              'approved_rendered_video':0}
    for path in PUB.glob('*.json'):
        if not HEX.fullmatch(path.name):continue
        rec=safe_record(path)
        counters['public_receipts']+=1
        if rec.get('status')=='PUBLIC_PUBLISHED_CONFIRMED':
            counters['public_confirmed']+=1
        elif rec.get('status')=='PUBLIC_SEND_UNCERTAIN_NO_RETRY':
            counters['public_uncertain']+=1
    for path in PRIVATE.glob('*.json'):
        if not HEX.fullmatch(path.name):continue
        rec=safe_record(path)
        if rec.get('status')=='PRIVATE_SENT_CONFIRMED':counters['private_confirmed']+=1
    for path in DEC.glob('*.json'):
        if not HEX.fullmatch(path.name):continue
        rec=safe_record(path)
        if rec.get('decision')=='editorially_accepted_not_published':counters['accepted']+=1
        if rec.get('decision')=='editorially_rejected':counters['rejected']+=1
    if WATERMARK.exists() and not WATERMARK.is_symlink():
        for p in WATERMARK.glob('*.json'):
            if not HEX.fullmatch(p.name):continue
            rec=safe_record(p)
            video_file=WATERMARK/(p.stem+'.mp4')
            if (rec.get('status')=='NAS_WATERMARK_RENDERED' and video_file.is_file()
                 and not video_file.is_symlink() and rec.get('sha256')):
                counters['approved_rendered_video']+=1
    issues=[k for k,v in requirements.items() if not v]
    # Approved watermark identity/position cannot be inferred from code existence.
    issues.append('APPROVED_WATERMARK_VISUAL_REFERENCE_NOT_VERIFIED')
    return {
       'schema':'RG_NEWS2_PUBLICATION_FOOTER_WM_READONLY_GATE_V1',
       'modules':modules,'requirements':requirements,'blockers':issues,
       'counts':counters,
       'watermark_png_candidates':watermark_candidates(),
       'passed_static_requirements':sum(requirements.values()),
       'total_static_requirements':len(requirements),
       'ready_to_install':False,  # explicit human-reviewed watermark is required
       'read_only':True,'telegram_api_calls':0,'production_writes':0,
       'publication_calls':0,'network_requests':0,
    }

def selftest():
    s="def publish_one():\n caption,caption_entities=append_footer(caption)\n"
    assert analyze_content(s)['has_footer_hook']
    assert not analyze_content(s)['has_idempotent_claim']
    assert HEX.fullmatch('a'*24+'.json')
    assert not HEX.fullmatch('a'*24+'.json/../../bad')
    print('NEWS2_PUBLICATION_FOOTER_WATERMARK_GATE_SELFTEST_PASS')

if __name__=='__main__':
    try:
        if sys.argv[1:]==['selftest']:selftest()
        elif sys.argv[1:]==['audit']:
            print(json.dumps(inspect(),ensure_ascii=False,sort_keys=True))
        else:raise Block('INVALID_MODE')
    except (Block,OSError,UnicodeError,ValueError) as e:
        print(json.dumps({'status':'SAFE_STOP','reason_class':type(e).__name__,
             'read_only':True,'telegram_api_calls':0,'production_writes':0}))
        raise SystemExit(2)
