#!/usr/bin/env python3
"""NEWS2 atomic, no-send installer for mandatory footer in existing publishers.

Only patches exact known transport calls in LIVE source, never replaces the
whole publisher with an older snapshot. Performs no Telegram API calls.
Requires a human-authorized root execution on NAS. Backup before change.
"""
import argparse
import ast
import fcntl
import hashlib
import json
import os
import pathlib
import stat
import subprocess
import tempfile
import time

O = pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
STAGED = pathlib.Path('/tmp/news_rg_required_footer_v1.py')
HELPER = O/'news_rg_required_footer_v1.py'
PHOTO = O/'news_rg_approved_publication_v1.py'
VIDEO = O/'news_rg_approved_video_publication_v1.py'
LOCK = O/'news_rg_publication.lock'
PINNED_BLOB = 'daec96d961280aab8812610ef24746a16e538c01'
MARK = '# RG_NEWS_REQUIRED_FOOTER_V1'
MAX_BYTES = 160000

class Stop(ValueError):pass

def git_sha(data):
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\x00'+data).hexdigest()

def checked_bytes(p, required=True):
    if p.is_symlink() or (not p.is_file() and required):
        raise Stop('UNSAFE_OR_MISSING_FILE_'+p.name)
    if not p.is_file():
        return None
    meta=p.stat()
    if not stat.S_ISREG(meta.st_mode) or not 0<meta.st_size<=MAX_BYTES:
        raise Stop('UNSAFE_FILE_SIZE_'+p.name)
    return p.read_bytes()

def replace_once(src, old, new, name):
    if src.count(old)!=1:
        raise Stop('SOURCE_CONTRACT_CHANGED_'+name)
    return src.replace(old,new,1)

def photo_patch(src):
    if MARK in src:
        for check in ('from news_rg_required_footer_v1 import format_post',
                      "'parse_mode':'HTML'", 'caption_html=format_post(caption)'):
            if check not in src:raise Stop('PARTIAL_PHOTO_INSTALL')
        return src,True
    src=replace_once(src,
        'import os,sys,re,json,time,pathlib,tempfile,urllib.request,urllib.parse,urllib.error,importlib.util,fcntl,hashlib',
        'import os,sys,re,json,time,pathlib,tempfile,urllib.request,urllib.parse,urllib.error,importlib.util,fcntl,hashlib\n'+
        MARK+'\nfrom news_rg_required_footer_v1 import format_post','PHOTO_IMPORT')
    src=replace_once(src,
        '  decision_at,key,photo,caption=selected\n  cfg=module();token=credentials()',
        '  decision_at,key,photo,caption=selected\n  caption_html=format_post(caption)\n  cfg=module();token=credentials()','PHOTO_PRECLAIM')
    src=replace_once(src,
        "'caption':caption,'disable_notification':'false'",
        "'caption':caption_html,'parse_mode':'HTML','disable_notification':'false'",
        'PHOTO_SEND')
    ast.parse(src)
    return src,False

def video_patch(src):
    if MARK in src:
        for check in ('from news_rg_required_footer_v1 import format_post',
                      "field('parse_mode','HTML')", 'caption_html=format_post(caption)'):
            if check not in src:raise Stop('PARTIAL_VIDEO_INSTALL')
        return src,True
    src=replace_once(src,
        'import os,sys,json,re,pathlib,time,hashlib,uuid,urllib.request,urllib.error,fcntl,importlib.util',
        'import os,sys,json,re,pathlib,time,hashlib,uuid,urllib.request,urllib.error,fcntl,importlib.util\n'+
        MARK+'\nfrom news_rg_required_footer_v1 import format_post','VIDEO_IMPORT')
    src=replace_once(src,
        '  when,key,video,expected,caption=selected\n  h=hashlib.sha256()',
        '  when,key,video,expected,caption=selected\n  caption_html=format_post(caption)\n  h=hashlib.sha256()','VIDEO_PRECLAIM')
    src=replace_once(src,
        "field('chat_id',channel);field('caption',caption);field('supports_streaming','true')",
        "field('chat_id',channel);field('caption',caption);field('parse_mode','HTML');field('supports_streaming','true')",
        'VIDEO_SEND')
    src=replace_once(src,
        "result=send_mp4(token,act['chat_id'],video,caption)",
        "result=send_mp4(token,act['chat_id'],video,caption_html)",
        'VIDEO_CALL')
    ast.parse(src)
    return src,False

def preflight():
    if os.geteuid()!=0:raise Stop('SUDO_REQUIRED')
    if not O.is_dir() or O.is_symlink():raise Stop('UNSAFE_OPERATOR_ROOT')
    stage=checked_bytes(STAGED)
    if git_sha(stage)!=PINNED_BLOB:raise Stop('FOOTER_SOURCE_HASH_MISMATCH')
    compile(stage.decode('utf-8'),'footer','exec')
    check=subprocess.run(['/usr/bin/python3',str(STAGED)],
                         capture_output=True,text=True,timeout=12)
    if check.returncode or 'RG_NEWS_REQUIRED_FOOTER_TELEGRAM_LENGTH_PASS' not in check.stdout:
        raise Stop('FOOTER_SELFTEST_FAILED')
    old_helper=checked_bytes(HELPER,False)
    if old_helper is not None and old_helper!=stage:
        raise Stop('DIFFERENT_HELPER_ALREADY_INSTALLED')
    original={p:checked_bytes(p) for p in (PHOTO,VIDEO)}
    current={p:original[p].decode('utf-8') for p in original}
    photo,already_photo=photo_patch(current[PHOTO])
    video,already_video=video_patch(current[VIDEO])
    if already_photo!=already_video:raise Stop('PARTIAL_PUBLISHER_INSTALL')
    patched={PHOTO:photo.encode('utf-8'),VIDEO:video.encode('utf-8')}
    return stage,original,patched,old_helper,already_photo

def atomic(p,data,mode):
    fd,tmp=tempfile.mkstemp(prefix='.rg_footer_',dir=str(p.parent))
    try:
        with os.fdopen(fd,'wb') as f:
            os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,p)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def install():
    if os.geteuid()!=0:raise Stop('SUDO_REQUIRED')
    fd=os.open(str(LOCK),os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        stage,original,patched,old_helper,already=preflight()
        if already and old_helper==stage:
            return {'status':'FOOTER_ALREADY_INSTALLED','writes':0,'telegram_sends':0}
        if already:raise Stop('HELPER_MISSING_PARTIAL_INSTALL')
        name='news_rg_footer_backup_'+time.strftime('%Y%m%d_%H%M%S',time.gmtime())
        backup=O/name
        if backup.exists() or backup.is_symlink():raise Stop('BACKUP_PATH_EXISTS')
        backup.mkdir(mode=0o700)
        changed=[]
        try:
            for p in (PHOTO,VIDEO):
                dst=backup/p.name
                with dst.open('xb') as f:f.write(original[p]);f.flush();os.fsync(f.fileno())
                os.chmod(dst,0o600)
            if old_helper is not None:
                dst=backup/HELPER.name
                with dst.open('xb') as f:f.write(old_helper);f.flush();os.fsync(f.fileno())
                os.chmod(dst,0o600)
            meta={'original_sha256':{p.name:hashlib.sha256(original[p]).hexdigest() for p in (PHOTO,VIDEO)},
                  'telegram_api_calls':0,'publications':0,'new_pollers':0}
            atomic(backup/'manifest.json',json.dumps(meta,sort_keys=True).encode(),0o600)
            atomic(HELPER,stage,0o600);changed.append(HELPER)
            for p in (PHOTO,VIDEO):
                atomic(p,patched[p],stat.S_IMODE(p.stat().st_mode));changed.append(p)
            for p in (PHOTO,VIDEO):
                test=subprocess.run(['/usr/bin/python3',str(p),'selftest'],
                     capture_output=True,text=True,timeout=12)
                if test.returncode or 'SELFTEST_PASS' not in test.stdout:
                    raise Stop('POSTINSTALL_SELFTEST_FAILED_'+p.name)
            return {'status':'NEWS2_FOOTER_INSTALLED','backup':str(backup),
                    'files_updated':len(changed),'telegram_sends':0,'publications':0,
                    'public_runner_shutdown_allowed':False}
        except Exception:
            for p in reversed(changed):
                if p==HELPER:
                    if old_helper is None:
                        if HELPER.is_file() and not HELPER.is_symlink():HELPER.unlink()
                    else:atomic(HELPER,old_helper,0o600)
                else:atomic(p,original[p],0o600)
            raise
    finally:
        os.close(fd)

def selftest():
    fixture_photo='''import os,sys,re,json,time,pathlib,tempfile,urllib.request,urllib.parse,urllib.error,importlib.util,fcntl,hashlib
def f():
  decision_at,key,photo,caption=selected
  cfg=module();token=credentials()
  d={'caption':caption,'disable_notification':'false'}
'''
    fixture_video='''import os,sys,json,re,pathlib,time,hashlib,uuid,urllib.request,urllib.error,fcntl,importlib.util
def f():
  when,key,video,expected,caption=selected
  h=hashlib.sha256()
  field('chat_id',channel);field('caption',caption);field('supports_streaming','true')
  result=send_mp4(token,act['chat_id'],video,caption)
'''
    a,_=photo_patch(fixture_photo);b,_=video_patch(fixture_video)
    assert photo_patch(a)==(a,True)
    assert video_patch(b)==(b,True)
    assert "'parse_mode':'HTML'" in a and "field('parse_mode','HTML')" in b
    assert a.index('caption_html=format_post(caption)')<a.index('cfg=module()')
    assert b.index('caption_html=format_post(caption)')<b.index('h=hashlib.sha256()')
    for func,source in ((photo_patch,fixture_photo),(video_patch,fixture_video)):
        try:func(source.replace('caption=selected','caption=wrong'))
        except Stop:pass
        else:raise AssertionError('DRIFT_ACCEPTED')
    print('NEWS2_FOOTER_ATOMIC_INSTALLER_SELFTEST_PASS')
    print('NEWS2_FOOTER_PRECLAIM_FORMATTING_GATE_PASS')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('action',choices=['selftest','preflight','install'])
    a=ap.parse_args()
    try:
        if a.action=='selftest':return selftest()
        if a.action=='preflight':
            _,_,_,_,already=preflight()
            print(json.dumps({'status':'ALREADY_INSTALLED' if already else 'PREFLIGHT_PASS',
                              'writes':0,'telegram_sends':0,'publications':0}))
        else:print(json.dumps(install(),sort_keys=True))
    except (Stop,OSError,UnicodeError,ValueError,RuntimeError,subprocess.TimeoutExpired) as e:
        print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:120],
                          'telegram_sends':0,'publications':0,'automatic_retry':False}))
        raise SystemExit(2)
if __name__=='__main__':main()
