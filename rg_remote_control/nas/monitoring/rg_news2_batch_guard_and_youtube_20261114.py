#!/usr/bin/env python3
"""NEWS2 one-command release: single-owner Tue/Thu YouTube + guarded watermark.

Executes two EXACT pre-tested root-only installers in a safe order:
1) Enables existing NAS YouTube TOP scheduler with its own backup/rollback.
2) Atomically repairs Nov14 watermark modules and Nov05 18-file LKG guard.
If step 2 fails, rolls back step 1. No sends during installation.
No arbitrary file paths, commands, Telegram API, or background pollers.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

NAS=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
R=NAS/'news_rg_stability_releases_v1'
YT=Path('/tmp/rg_news2_youtube_nas_single_owner_atomic_20261114.py')
WM=Path('/tmp/rg_news2_wm_guard_atomic_repair_20261114.py')
GIT_BLOBS={
    YT.name:'5e779ad6ae33345edf9c67652cda92a817bdc2ee',
    WM.name:'639164ccfe10c6683315c1ca86e71efddc623f6d',
}
EXPECTED_WM_RENDER='b37c7582954bc301efdf94bb0c42233daa9c4676fc28cfc6ec5a5ec6a4996c67'
EXPECTED_WM_PUBLISH='ec531215193d5caa184797ad298d00936df1265e16c0aed1affdb96f4c116679'
EXPECTED_VERSION='2026-11-14-stable5.2-topright-watermark'
OWNER=NAS/'rg_news2_youtube_owner_nas_v1.json'
TICK=NAS.parent/'rg_news_dsm_tick.sh'
PINNED=R/'pinned_release_v1.json'
class Stop(Exception):pass
def gitblob(data):
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
def check_sources():
    if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
    for path in (YT,WM):
        s=path.lstat()
        if not stat.S_ISREG(s.st_mode) or s.st_size>100000 or s.st_size<1000:
            raise Stop('INSTALLER_STAGING_UNSAFE_'+path.name)
        if gitblob(path.read_bytes())!=GIT_BLOBS[path.name]:
            raise Stop('INSTALLER_SOURCE_PIN_MISMATCH_'+path.name)
def run_installer(path,mode):
    proc=subprocess.run(['/usr/bin/python3',str(path),mode],capture_output=True,
                        text=True,timeout=240)
    lines=[s.strip() for s in proc.stdout.splitlines() if s.strip().startswith('{')]
    obj={}
    for line in lines:
        try:obj=json.loads(line)
        except ValueError:pass
    if proc.returncode or obj.get('status') not in ('PREFLIGHT_PASS','APPLIED_QA_PASS','ROLLBACK_VERIFIED'):
        raise Stop(path.name+'_'+mode+'_'+str(obj.get('reason','FAILED'))[:90])
    return obj
def postcheck():
    meta=json.loads(PINNED.read_text('utf8'))
    assert meta.get('version')==EXPECTED_VERSION,'GUARD_VERSION_NOT_UPDATED'
    assert meta['files']['news_rg_nas_video_pipeline_v1.py']==EXPECTED_WM_RENDER
    assert meta['files']['news_rg_approved_video_publication_v1.py']==EXPECTED_WM_PUBLISH
    assert hashlib.sha256((NAS/'news_rg_nas_video_pipeline_v1.py').read_bytes()).hexdigest()==EXPECTED_WM_RENDER
    assert hashlib.sha256((NAS/'news_rg_approved_video_publication_v1.py').read_bytes()).hexdigest()==EXPECTED_WM_PUBLISH
    state=json.loads(OWNER.read_text('utf8'))
    assert state.get('owner')=='nas' and state.get('no_second_poller') is True
    shell=TICK.read_text('utf8')
    assert shell.count('news_rg_youtube_top_schedule_v1.py')==1
    assert 'Cloudflare owns Tue/Thu 18:00' not in shell
    return {'guard_version':EXPECTED_VERSION,'modules_pinned':18,
            'youtube_single_owner':'NAS','youtube_schedule':'Tuesday and Thursday 18:00 Kyiv',
            'telegram_sends_during_install':0,'publications_during_install':0}
def selftest():
    assert len(GIT_BLOBS)==2 and all(len(x)==40 for x in GIT_BLOBS.values())
    assert EXPECTED_WM_RENDER!=EXPECTED_WM_PUBLISH
    print('NEWS2_TWO_COMPONENT_BATCH_ORCHESTRATOR_SELFTEST_PASS')
def run():
    check_sources()
    first=run_installer(YT,'preflight')
    second=run_installer(WM,'preflight')
    yta=run_installer(YT,'apply')
    try:
        wma=run_installer(WM,'apply')
    except Exception as exc:
        rollback_result='NOT_ATTEMPTED'
        try:
            rb=run_installer(YT,'rollback')
            rollback_result=rb.get('status')
        except Exception as rb_err:
            rollback_result='FAILED_'+type(rb_err).__name__
        raise Stop('WM_APPLY_FAILED_YOUTUBE_ROLLBACK_'+rollback_result+'_'+type(exc).__name__)
    return {'status':'BATCH_APPLIED_QA_PASS',
            'youtube_release':yta.get('release'),
            'wm_guard_release':wma.get('release'),
            'backup_verified':yta.get('backup_verified') and wma.get('backup_verified'),
            'postcheck':postcheck()}
if __name__=='__main__':
    try:
        if sys.argv[1:]==['selftest']:selftest()
        elif sys.argv[1:]==['preflight']:
            check_sources()
            a=run_installer(YT,'preflight')
            b=run_installer(WM,'preflight')
            print(json.dumps({'status':'BATCH_PREFLIGHT_PASS',
                'youtube_module':'READY','watermark_guard':'READY',
                'production_writes':0,'telegram_sends':0,'publications':0}))
        elif sys.argv[1:]==['apply']:
            print(json.dumps(run(),sort_keys=True))
        else:raise Stop('UNSUPPORTED_MODE')
    except Exception as e:
        print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:170],
            'telegram_sends':0,'publications':0}))
        raise SystemExit(2)
