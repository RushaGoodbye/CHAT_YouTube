#!/usr/bin/env python3
"""NEWS2 release 2 offline QA bundle and root-only live read-only preflight.

No installs, no Telegram, no modifications. Files must all match pinned Git
blob identities. Never trust arbitrary source files supplied by the caller.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

DIR=Path('/tmp')
SOURCES={
 'rg_news2_publication_footer_wm_readonly_gate_v1.py':'53645782632605c309f75a0bac69f2da95861d88',
 'rg_news2_footer_entities_contract_v2.py':'d3e8bd8f2926d150ed4796da33dd74e6704dc46f',
 'rg_news2_watermark_manifest_gate_v1.py':'6c08757e670fb1d95806157bea2c37084450292e',
 'rg_news2_prepublication_contract_v1.py':'466e8ce498cb6c3590827d0b5aa5d672cdaca71c',
}
class QAStop(ValueError):pass

def gitblob(b):return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()

def check():
    for name,sha in SOURCES.items():
        p=DIR/name
        st=p.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_size>150000 or st.st_size<10:
            raise QAStop('UNSAFE_SOURCE_'+name)
        if gitblob(p.read_bytes())!=sha:
            raise QAStop('SOURCE_CHECKSUM_MISMATCH_'+name)

def test():
    check()
    results={}
    for file in SOURCES:
        cmd=[sys.executable,str(DIR/file)]
        if 'readonly_gate' in file:cmd+=['selftest']
        out=subprocess.run(cmd,capture_output=True,text=True,
            timeout=25,env=dict(os.environ,PYTHONPATH=str(DIR)))
        if out.returncode or 'PASS' not in out.stdout:
            raise QAStop('TEST_FAILED_'+file)
        results[file]={'status':'PASS','test_summary':out.stdout.strip().splitlines()[-1]}
    return {'status':'OFFLINE_QA_PASS_NOT_INSTALLED',
            'components':results,'source_hashes_pinned':True,
            'publication_enabled':False,'production_changes':0,
            'telegram_calls':0,'publications':0}

def live_audit():
    if os.geteuid()!=0:raise QAStop('ROOT_REQUIRED')
    test()
    import importlib.util
    p=DIR/'rg_news2_publication_footer_wm_readonly_gate_v1.py'
    spec=importlib.util.spec_from_file_location('news2_release2_live_gate',str(p))
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    r=mod.inspect()
    # Prevent any temptation to treat the read-only audit as a deployment.
    return {'status':'LIVE_READONLY_PREFLIGHT',
            'static_checks_passed':r['passed_static_requirements'],
            'static_checks_total':r['total_static_requirements'],
            'static_failures':[k for k,v in r['requirements'].items() if not v],
            'visual_reference_approved':False,
            'ready_to_install':False,
            'production_changes':0,'publications':0,'telegram_calls':0}

if __name__=='__main__':
    try:
        if sys.argv[1:]==['selftest']:
            print(json.dumps(test(),ensure_ascii=False,sort_keys=True))
        elif sys.argv[1:]==['live-preflight']:
            print(json.dumps(live_audit(),ensure_ascii=False,sort_keys=True))
        else:raise QAStop('UNSUPPORTED_MODE')
    except (QAStop,OSError,UnicodeError,ValueError,subprocess.TimeoutExpired) as e:
        print(json.dumps({'status':'SAFE_STOP','error':str(e)[:100],
             'production_changes':0,'telegram_calls':0,'publications':0}))
        raise SystemExit(2)
