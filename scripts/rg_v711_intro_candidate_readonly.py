"""RG Full Stream V7.11 CANDIDATE, intro scan limit only.

Default is inspection without file writes. Only a future approved release
installer may invoke --apply, and only with Studio/worker processes stopped.

No changes to originals, MP4, XML, dialogue clips, queue or runtime on import.
"""
from __future__ import annotations
import argparse,ast,hashlib,json,os,re,subprocess,sys,time,uuid
from pathlib import Path

CANON=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit App')
LOCAL=Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData'/'Local')/'Programs'/'RG Auto Edit'
TARGET='rg_fullstream_policy_v70.py'
EXPECTED='599e1490590ffd0fda871ed5f94ea772ef7ea75a01aa19c5fdd8fd274c01908f'
OLD='max_search=900, sample_step=.5'
NEW='max_search=3600, sample_step=.5'

def hashbytes(raw: bytes)->str:return hashlib.sha256(raw).hexdigest()

def patch(raw: bytes)->bytes:
    if hashbytes(raw)!=EXPECTED:raise RuntimeError('UNRECOGNIZED_PRODUCTION_POLICY_SHA')
    text=raw.decode('utf-8-sig')
    if text.count(OLD)!=1 or text.count('def intro_color_host_start(')!=1:
        raise RuntimeError('INTRO_POLICY_SIGNATURE_MISMATCH')
    updated=text.replace(OLD,NEW,1)
    ast.parse(updated,filename=TARGET)
    # Keep original newline convention and UTF8 BOM if any.
    return (b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'')+updated.encode('utf-8')

def inspect():
    result=[]
    for name,root in [('CANONICAL',CANON),('LOCAL_GUI',LOCAL)]:
        path=root/TARGET
        if not path.is_file():raise RuntimeError('ROOT_MISSING_'+name)
        raw=path.read_bytes()
        if hashbytes(raw)==EXPECTED:
            new=patch(raw);state='PATCH_REQUIRED'
        elif raw.count(NEW.encode())==1 and raw.count(OLD.encode())==0:
            new=raw;state='ALREADY_PATCHED'
        else:raise RuntimeError('ROOT_SHA_UNRECOGNIZED_'+name)
        result.append((name,path,raw,new,state))
    if len({hashbytes(row[2]) for row in result})!=1:
        raise RuntimeError('CANONICAL_LOCAL_ROOT_DIVERGED')
    return result

def require_idle():
    if os.name!='nt':raise RuntimeError('WINDOWS_ONLY')
    ps=r'''$p=@(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
      ($_.Name -match '^(pythonw?\.exe|ffmpeg\.exe|RG Auto Edit.*\.exe)$') -and
      (($_.CommandLine -match '(?i)rg_fullstream_(worker_v3|auto_v2|batch_v53|launcher_v2)\.py|rg_studio_ui\.py|rg_studio_main\.py') -or
      ($_.Name -match '^RG Auto Edit') -or
      ($_.Name -eq 'ffmpeg.exe' -and $_.CommandLine -match '(?i)RG_AUTO_EDIT|FULLSTREAM_YOUTUBE'))
    } | Select-Object -ExpandProperty ProcessId)
    ConvertTo-Json -InputObject $p -Compress'''
    proc=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',ps],
                        capture_output=True,text=True,timeout=45)
    if proc.returncode:raise RuntimeError('PROCESS_INSPECTION_FAILED')
    try:active=json.loads(proc.stdout.strip() or '[]')
    except ValueError:raise RuntimeError('PROCESS_INSPECTION_INVALID_JSON')
    if active:raise RuntimeError('STUDIO_OR_VIDEO_WORKER_ACTIVE_REFUSE_PATCH')
    sys.path.insert(0,str(CANON))
    from rg_fullstream_process_state_v59 import worker_lock_state
    if worker_lock_state(Path(r'F:\RG_AUTO_EDIT\RG Auto Edit Data'))!='IDLE':
        raise RuntimeError('FULLSTREAM_GPU_WORKER_LOCK_NOT_IDLE')
    import rg_fullstream_exit_v66
    if rg_fullstream_exit_v66.inventory():raise RuntimeError('RG_OWNED_WORKERS_ACTIVE')

def apply(roots):
    require_idle()
    roots=inspect()
    todo=[x for x in roots if x[4]=='PATCH_REQUIRED']
    if not todo:return 'ALREADY_INSTALLED'
    folder=Path.home()/'Downloads'/('RG_V711_INTRO_BACKUP_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
    folder.mkdir(parents=True,exist_ok=False)
    changes=[]
    try:
        for name,path,raw,new,_ in todo:
            backup=folder/(name+'_'+TARGET+'.bak')
            backup.write_bytes(raw)
            staged=path.with_name(path.name+'.v711_'+uuid.uuid4().hex+'.tmp')
            try:
                staged.write_bytes(new)
                if hashbytes(staged.read_bytes())!=hashbytes(new):raise RuntimeError('STAGED_HASH_MISMATCH')
                os.replace(staged,path)
                changes.append((path,backup))
            finally:staged.unlink(missing_ok=True)
        if any(x[4]!='ALREADY_PATCHED' for x in inspect()):raise RuntimeError('POST_PATCH_VERIFICATION_FAILED')
    except BaseException:
        for path,backup in reversed(changes):os.replace(backup,path)
        print('RG_V711|ROLLBACK|DONE',flush=True)
        raise
    return 'INTRO_ONLY_APPLIED_BACKUP='+str(folder)

def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('--apply',action='store_true');args=ap.parse_args(argv)
    roots=inspect()
    for name,_,raw,new,status in roots:
        print('RG_V711|PREFLIGHT|'+name+'|'+status+'|'+hashbytes(raw)+'|'+hashbytes(new),flush=True)
    if not args.apply:
        print('RG_V711|DRY_RUN|PASS|NO_FILES_MODIFIED|INTRO_ONLY',flush=True)
        return 0
    print('RG_V711|'+apply(roots),flush=True)
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:
        print('RG_V711|STOP|'+type(e).__name__+':'+str(e)[:220],flush=True)
        raise SystemExit(2)