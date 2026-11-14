#!/usr/bin/env python3
"""NEWS2 P2 pinned atomic patch: UTF-16 caption length in LIVE footer.

PINNED to 2026-11-14 verified NAS photo/video/text publishers, renderer,
scheduler and approved Nov 4 watermark asset. No Telegram API, public
publication, scheduler changes, photo/video code changes or pollers.

Full backup, shared publication lock, atomic replace, live postinstall
selftest+UTF16 regression, and automatic rollback. One fixed patch only.
"""
import datetime,fcntl,hashlib,importlib.util,json,os,stat,sys,tempfile
from pathlib import Path

OP=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
TARGET=OP/'news_rg_project_footer_v1.py'
LOCK=OP/'news_rg_publication.lock'
BK=OP/'rg_news2_release_backups_v2'/'footer_utf16_20261114'
OLD=BK/'footer_before.py'
REC=BK/'receipt.json'
PIN={
  'news_rg_approved_publication_v1.py':'d8a333858dd1e18eb77d2b3cc7ccf4cb5e276f6bf3f2dc8d084ffa12c1a6d9d6',
  'news_rg_approved_video_publication_v1.py':'7a3fdfdd443803834c0da18a05d3a5cde512ed34322e64bce89255d68a6dd395',
  'news_rg_approved_text_publication_v1.py':'f4c97569e7cbe432aa73a0bed5ef37875257fe158905c9dd96d83a24ecccb d45'.replace(' ',''),
  'news_rg_project_footer_v1.py':'eec7e0de9d013decd0f990faa366f1151e5cf1a8ec7264d5861499b991caf933',
  'news_rg_nas_video_pipeline_v1.py':'59b87da6057482702807837948da46307396fc4e63e2a2fc7c181ec692c10e55',
  'news_rg_publication_schedule_v1.py':'0ce0e62d04b13a7bd62a1d792c3553bc67103d1be701b720125582e5326af530',
  'assets/rg_approved_watermark_20261104.png':'1e852e8540d079ebf275294a784559557098dab455f14bcfa1efe86152b73585',
}
# Exact existing known line. No generalized regex or arbitrary patch.
BEFORE='if len(prefix)+len(FOOTER_TEXT)>1024:raise ValueError("PUBLIC_FOOTER_CAPTION_TOO_LONG")'
AFTER='if _length(prefix)+_length(FOOTER_TEXT)>1024:raise ValueError("PUBLIC_FOOTER_CAPTION_TOO_LONG")'
class Halt(ValueError):pass

def hashbytes(raw):return hashlib.sha256(raw).hexdigest()

def regular(path,expected=None):
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_size<1 or s.st_size>300000:
        raise Halt('FILE_UNSAFE_'+path.name)
    raw=path.read_bytes()
    if expected and hashbytes(raw)!=expected:raise Halt('FILE_HASH_DRIFT_'+path.name)
    return raw

def rootdir(path,create=False):
    if create and not path.exists():path.mkdir(mode=0o700)
    s=path.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:
        raise Halt('DIR_UNSAFE_'+path.name)

def source_patch(raw):
    src=raw.decode('utf-8')
    if src.count(BEFORE)!=1 or AFTER in src:raise Halt('FOOTER_SOURCE_CONTRACT_DRIFT')
    return src.replace(BEFORE,AFTER,1).encode('utf-8')

def footer_test(sourcebytes):
    # Compile isolated footer module and exercise both regular and emoji content.
    with tempfile.TemporaryDirectory(prefix='rg_news2_footer_qa_') as d:
        q=Path(d)/'footer.py'
        q.write_bytes(sourcebytes)
        spec=importlib.util.spec_from_file_location('_rg_footer_test',str(q))
        m=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        m.selftest()
        caption,entities=m.append_footer('💥 Новина з України')
        assert len(caption.encode('utf-16-le'))//2<=1024
        assert entities[0]['type']=='bold' and entities[1]['type']=='text_link'
        assert entities[0]['offset']==len('💥 Новина з України\n\n'.encode('utf-16-le'))//2
        assert entities[0]['length']==entities[1]['length']
        assert entities[1]['url']=='https://links.rginfoua.pp.ua/'
        # Old code wrongly accepts this because len(text) counts codepoints not UTF-16.
        over='💥'*505+'Новина'
        assert len(over)<1024
        assert len(over.encode('utf-16-le'))//2>1000
        try:m.append_footer(over)
        except ValueError as e:assert 'PUBLIC_FOOTER_CAPTION_TOO_LONG' in str(e)
        else:raise Halt('UTF16_EMOJI_REGRESSION_FAILED')
        assert m.append_footer(m.append_footer('Текст новини')[0])[0]==m.append_footer('Текст новини')[0]
    return True

def contracts():
    rootdir(OP)
    for name,expected in PIN.items():
        regular(OP/name,expected)
    photo=(OP/'news_rg_approved_publication_v1.py').read_text(encoding='utf-8')
    video=(OP/'news_rg_approved_video_publication_v1.py').read_text(encoding='utf-8')
    text=(OP/'news_rg_approved_text_publication_v1.py').read_text(encoding='utf-8')
    render=(OP/'news_rg_nas_video_pipeline_v1.py').read_text(encoding='utf-8')
    for src in (photo,video,text):
        if 'PUBLIC_SEND_UNCERTAIN_NO_RETRY' not in src or 'append_footer(' not in src:
            raise Halt('PUBLISHER_SAFETY_CONTRACT_DRIFT')
    if 'sendMediaGroup' not in photo or "caption_entities" not in photo:
        raise Halt('PHOTO_ALBUM_FOOTER_MISSING')
    if 'watermark_asset_sha256' not in video or 'APPROVED_LOGO_SHA256' not in video:
        raise Halt('WM_VIDEO_HASH_GATE_MISSING')
    if 'APPROVED_LOGO_SHA256' not in render:
        raise Halt('WM_RENDER_HASH_GATE_MISSING')
    profile=OP/'assets/approved_watermark_profile_20261104.json'
    p=json.loads(regular(profile))
    if p.get('sha256')!=PIN['assets/rg_approved_watermark_20261104.png'] or p.get('watermark_profile')!='RG_APPROVED_20261104_CENTER_040_078':
        raise Halt('STORED_APPROVED_WM_PROFILE_DRIFT')
    return True

def preflight():
    if os.geteuid()!=0:raise Halt('ROOT_REQUIRED')
    if TARGET.is_symlink() or LOCK.is_symlink() or BK.is_symlink() or BK.parent.is_symlink():
        raise Halt('UNSAFE_SYMLINK')
    contracts()
    original=regular(TARGET,PIN['news_rg_project_footer_v1.py'])
    updated=source_patch(original)
    footer_test(updated)
    return original,updated

def atomic(path,raw,mode):
    fd,tmp=tempfile.mkstemp(prefix='.news2_footer_release_',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as f:
            os.fchmod(f.fileno(),mode)
            f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def lock():
    if LOCK.is_symlink():raise Halt('LOCK_SYMLINK')
    fd=os.open(str(LOCK),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    return fd

def apply():
    before,patched=preflight()
    fd=lock()
    try:
        regular(TARGET,PIN['news_rg_project_footer_v1.py'])
        rootdir(BK.parent,create=True);rootdir(BK,create=True)
        if OLD.exists() or REC.exists():raise Halt('RELEASE_ALREADY_STARTED')
        atomic(OLD,before,0o600)
        regular(OLD,hashbytes(before))
        oldmode=stat.S_IMODE(TARGET.stat().st_mode)
        try:
            atomic(TARGET,patched,oldmode)
            regular(TARGET,hashbytes(patched))
            footer_test(regular(TARGET))
            record={
                'status':'APPLIED_QA_PASS','release':'NEWS2_FOOTER_UTF16_20261114',
                'sha256_before':hashbytes(before),'sha256_after':hashbytes(patched),
                'applied_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'backup_verified':True,'telegram_calls':0,'publications':0,
                'photo_video_text_publishers_unchanged':True,
                'watermark_profile_unchanged':True,
            }
            atomic(REC,(json.dumps(record,sort_keys=True)+'\n').encode('utf-8'),0o600)
            return record
        except Exception:
            atomic(TARGET,before,oldmode)
            regular(TARGET,hashbytes(before))
            raise
    finally:os.close(fd)

def rollback():
    if os.geteuid()!=0:raise Halt('ROOT_REQUIRED')
    rootdir(BK.parent);rootdir(BK)
    before=regular(OLD,PIN['news_rg_project_footer_v1.py'])
    receipt=json.loads(regular(REC))
    if receipt.get('status')!='APPLIED_QA_PASS' or receipt.get('sha256_before')!=hashbytes(before):
        raise Halt('RECEIPT_INVALID')
    current=regular(TARGET,receipt.get('sha256_after'))
    fd=lock()
    try:
        regular(TARGET,receipt.get('sha256_after'))
        atomic(TARGET,before,stat.S_IMODE(TARGET.stat().st_mode))
        regular(TARGET,PIN['news_rg_project_footer_v1.py'])
        return {'status':'ROLLBACK_VERIFIED','telegram_calls':0,'publications':0}
    finally:os.close(fd)

def selftest():
    assert len(PIN)==7
    assert PIN['news_rg_project_footer_v1.py'].startswith('eec7e0de')
    assert BEFORE!=AFTER and BEFORE.count('len(')==2 and AFTER.count('_length(')==2
    print('NEWS2_FOOTER_ATOMIC_INSTALLER_SELFTEST_PASS')

if __name__=='__main__':
    try:
        if sys.argv[1:]==['selftest']:selftest()
        elif sys.argv[1:]==['preflight']:
            preflight()
            print(json.dumps({'status':'PREFLIGHT_PASS','target':'FOOTER_UTF16_ONLY','publications':0}))
        elif sys.argv[1:]==['apply']:print(json.dumps(apply(),sort_keys=True))
        elif sys.argv[1:]==['rollback']:print(json.dumps(rollback(),sort_keys=True))
        else:raise Halt('BAD_MODE')
    except Exception as e:
        print(json.dumps({'status':'SAFE_STOP','reason':str(e)[:130],'publications':0,'telegram_calls':0}))
        raise SystemExit(2)
