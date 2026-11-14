#!/usr/bin/env python3
"""NEWS2 Tue/Thu YouTube top-video selector: OFFLINE PLAN ONLY.

This is deliberately not a publisher, does not make network requests, does not
obtain credentials, and never modifies any ledger. The source catalog must
be verified separately and the output must pass existing moderation, video
watermark and idempotent publication gates before any future integration.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time

CHANNEL = 'https://www.youtube.com/@RussiaGoodbye'
ALLOWED_WEEKDAYS = (1,3)  # Tuesday / Thursday; Monday=0.
MAX_TOP = 20
VIDEO = re.compile(r'^[A-Za-z0-9_-]{11}$')
class GateError(ValueError): pass

def safe_json(p,limit):
    if p.is_symlink() or not p.is_file() or p.stat().st_size>limit:
        raise GateError('UNSAFE_OR_MISSING_INPUT')
    try: val=json.loads(p.read_text(encoding='utf8'))
    except (UnicodeError,ValueError,OSError):raise GateError('INVALID_JSON')
    return val

def verified_catalog(doc):
    if not isinstance(doc,dict) or doc.get('schema')!='RG_VERIFIED_TOP_VIDEOS_V1':
        raise GateError('CATALOG_SCHEMA')
    if doc.get('channel')!=CHANNEL:raise GateError('CHANNEL_NOT_VERIFIED')
    asof=doc.get('verified_at_unix')
    if type(asof)!=int or asof<=1700000000 or asof>time.time()+300 or time.time()-asof>7*86400:
        raise GateError('CATALOG_TOO_OLD_OR_UNVERIFIED')
    videos=doc.get('videos')
    if not isinstance(videos,list) or not 3<=len(videos)<=MAX_TOP:
        raise GateError('CATALOG_LENGTH')
    seen=set();out=[];ranks=set()
    for d in videos:
        if not isinstance(d,dict):raise GateError('CATALOG_ITEM')
        vid=d.get('id');rank=d.get('rank');views=d.get('views')
        if not isinstance(vid,str) or not VIDEO.fullmatch(vid) or vid in seen:
            raise GateError('VIDEO_ID_OR_DUPLICATE')
        if type(rank)!=int or not 1<=rank<=MAX_TOP or rank in ranks:
            raise GateError('VIDEO_RANK_OR_DUPLICATE')
        if type(views)!=int or views<1000:raise GateError('VIDEO_VIEWS_INVALID')
        seen.add(vid);ranks.add(rank)
        out.append({'id':vid,'rank':rank,'views':views})
    if sorted(ranks)!=list(range(1,len(videos)+1)):
        raise GateError('RANK_GAP')
    out.sort(key=lambda d:d['rank'])
    # The catalog is already ranked: prevents unverified source-as-top claims.
    if any(a['views']<b['views'] for a,b in zip(out,out[1:])):
        raise GateError('VIEWS_NOT_RANKED')
    return out

def prior_ids(doc):
    if not isinstance(doc,dict) or doc.get('schema')!='RG_YOUTUBE_VIDEO_PUBLICATION_LEDGER_V1':
        raise GateError('LEDGER_SCHEMA')
    records=doc.get('published')
    if not isinstance(records,list) or len(records)>10000:raise GateError('LEDGER_LENGTH')
    result=set()
    for row in records:
        if not isinstance(row,dict):raise GateError('LEDGER_ROW')
        vid=row.get('id')
        if not isinstance(vid,str) or not VIDEO.fullmatch(vid):raise GateError('LEDGER_VIDEO_ID')
        if row.get('status')!='PUBLIC_PUBLISHED_CONFIRMED':
            raise GateError('LEDGER_UNCONFIRMED_ROW')
        result.add(vid)
    return result

def select(doc,ledger,at=None,chooser=None):
    # DSM host local timezone MUST already be Europe/Kyiv; validate explicitly.
    zone=os.environ.get('TZ')
    if zone!='Europe/Kyiv':raise GateError('TZ_MUST_BE_EUROPE_KYIV')
    if at is None:at=datetime.datetime.now()
    if at.tzinfo is not None:raise GateError('EXPECT_LOCAL_NAIVE_DATETIME')
    if at.weekday() not in ALLOWED_WEEKDAYS:
        return {'status':'DAY_NOT_ELIGIBLE','publications':0,'telegram_calls':0}
    pool=verified_catalog(doc);posted=prior_ids(ledger)
    # Cycle exhausted means STOP; do not silently re-post.
    avail=[d for d in pool if d['id'] not in posted]
    if not avail:return {'status':'TOP_POOL_EXHAUSTED_NEEDS_REVIEW','publications':0,'telegram_calls':0}
    chooser=chooser or secrets.SystemRandom()
    item=chooser.choice(avail)
    return {'status':'OFFLINE_CANDIDATE_ONLY',
            'date_kyiv':at.strftime('%Y-%m-%d'),
            'video_id':item['id'],'rank':item['rank'],
            'source_channel':CHANNEL,
            'watermark':'NOT_VERIFIED',
            'mod_approval':'NOT_VERIFIED',
            'publication':'OFF',
            'publications':0,'telegram_calls':0}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['selftest','plan'])
    parser.add_argument('--catalog');parser.add_argument('--ledger')
    a=parser.parse_args()
    if a.mode=='selftest':
        class First:
            def choice(self,arr):return arr[0]
        now=int(time.time())
        cat={'schema':'RG_VERIFIED_TOP_VIDEOS_V1','channel':CHANNEL,'verified_at_unix':now,
             'videos':[{'id':x*11,'rank':i+1,'views':10000-i*1000} for i,x in enumerate('abc')]}
        led={'schema':'RG_YOUTUBE_VIDEO_PUBLICATION_LEDGER_V1','published':[]}
        old=os.environ.get('TZ');os.environ['TZ']='Europe/Kyiv'
        try:
            assert select(cat,led,datetime.datetime(2026,11,17,12),First())['video_id']=='a'*11
            assert select(cat,led,datetime.datetime(2026,11,19,12),First())['status']=='OFFLINE_CANDIDATE_ONLY'
            assert select(cat,led,datetime.datetime(2026,11,14,12),First())['status']=='DAY_NOT_ELIGIBLE'
            led['published']=[{'id':x*11,'status':'PUBLIC_PUBLISHED_CONFIRMED'} for x in 'abc']
            assert select(cat,led,datetime.datetime(2026,11,17,12),First())['status']=='TOP_POOL_EXHAUSTED_NEEDS_REVIEW'
            cat['videos'][0]['id']='bad'
            try:select(cat,{'schema':'RG_YOUTUBE_VIDEO_PUBLICATION_LEDGER_V1','published':[]},datetime.datetime(2026,11,17,12),First())
            except GateError:pass
            else:raise AssertionError('BAD_ID_NOT_REJECTED')
        finally:
            if old is None:os.environ.pop('TZ',None)
            else:os.environ['TZ']=old
        print('NEWS2_YOUTUBE_TUE_THU_OFFLINE_PLANNER_5_CASES_PASS')
        print('NO_TELEGRAM_NO_PUBLISH_NO_LEDGER_WRITES_PASS')
        return
    if not a.catalog or not a.ledger:raise GateError('REQUIRED_VERIFIED_INPUTS_MISSING')
    print(json.dumps(select(safe_json(Path(a.catalog),50000),safe_json(Path(a.ledger),700000)),sort_keys=True))
if __name__=='__main__':
    try:main()
    except (GateError,OSError) as e:
        print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:70],'publications':0,'telegram_calls':0}))
        raise SystemExit(2)
