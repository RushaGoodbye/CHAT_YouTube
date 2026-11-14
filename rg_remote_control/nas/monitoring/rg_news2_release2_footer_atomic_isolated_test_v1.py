#!/usr/bin/env python3
"""Run release2 footer install and QA-failure rollback against temp fixtures only."""
import importlib.util
from pathlib import Path
import os
import tempfile
M=Path('/tmp/rg_news2_release2_footer_utf16_atomic_v1.py')

source='''FOOTER_TEXT='УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ "РАША ГУДБАЙ"'
FOOTER_URL='https://links.rginfoua.pp.ua/'
def _length(s):return len(s.encode("utf-16-le"))//2
def append_footer(text):
 value=str(text or "").strip()
 if value.endswith(FOOTER_TEXT):value=value[:-len(FOOTER_TEXT)].rstrip()
 prefix=value+"\\n\\n" if value else ""
 if len(prefix)+len(FOOTER_TEXT)>1024:raise ValueError("PUBLIC_FOOTER_CAPTION_TOO_LONG")
 offset=_length(prefix);size=_length(FOOTER_TEXT)
 return prefix+FOOTER_TEXT,[{"type":"bold","offset":offset,"length":size},
   {"type":"text_link","offset":offset,"length":size,"url":FOOTER_URL}]
def selftest():
 m,e=append_footer("💥 Новина")
 assert m.endswith(FOOTER_TEXT)
'''

def run():
 spec=importlib.util.spec_from_file_location('pinned_footer_installer_test',str(M))
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 old=source.encode('utf-8')
 new=mod.source_patch(old)
 assert mod.BEFORE.encode() in old
 assert mod.AFTER.encode() in new
 # Fixture does not match source layout, but must pass actual postinstall
 # UTF16 assertions; the input creates a test module, not a production path.
 mod.footer_test(new)
 with tempfile.TemporaryDirectory(prefix='news2_footer_atomic_test_') as temp:
  root=Path(temp)
  old_paths={k:getattr(mod,k) for k in ('OP','TARGET','LOCK','BK','OLD','REC')}
  orig_preflight=mod.preflight
  orig_rootdir=mod.rootdir
  orig_geteuid=mod.os.geteuid
  orig_hash=mod.PIN['news_rg_project_footer_v1.py']
  orig_footer_test=mod.footer_test
  try:
   mod.OP=root;mod.TARGET=root/'footer.py';mod.TARGET.write_bytes(old)
   mod.LOCK=root/'pub.lock';mod.BK=root/'backups'/'version';mod.OLD=mod.BK/'before.py';mod.REC=mod.BK/'receipt.json'
   mod.PIN['news_rg_project_footer_v1.py']=mod.hashbytes(old)
   mod.preflight=lambda:(old,new)
   mod.rootdir=lambda p,create=False:p.mkdir(mode=0o700,parents=True,exist_ok=True) if create else None
   mod.os.geteuid=lambda:0
   result=mod.apply()
   assert result['status']=='APPLIED_QA_PASS'
   assert mod.TARGET.read_bytes()==new and mod.OLD.read_bytes()==old
   assert mod.REC.is_file()
   back=mod.rollback()
   assert back['status']=='ROLLBACK_VERIFIED'
   assert mod.TARGET.read_bytes()==old
   print('NEWS2_FOOTER_RELEASE_ISOLATED_APPLY_BACKUP_ROLLBACK_PASS')
   # Separate clean fixture for a simulated postinstall QA failure.
   mod.BK=root/'backups'/'version2';mod.OLD=mod.BK/'before.py';mod.REC=mod.BK/'receipt.json'
   mod.footer_test=lambda _: (_ for _ in ()).throw(RuntimeError('SIMULATED_FOOTER_QA_FAIL'))
   try:mod.apply()
   except RuntimeError as e:assert str(e)=='SIMULATED_FOOTER_QA_FAIL'
   else:raise AssertionError('EXPECTED_QA_FAILURE')
   assert mod.TARGET.read_bytes()==old
   assert not mod.REC.exists()
   assert mod.OLD.read_bytes()==old
   print('NEWS2_FOOTER_RELEASE_ISOLATED_POSTINSTALL_AUTO_ROLLBACK_PASS')
  finally:
   for k,v in old_paths.items():setattr(mod,k,v)
   mod.preflight=orig_preflight;mod.rootdir=orig_rootdir
   mod.os.geteuid=orig_geteuid
   mod.PIN['news_rg_project_footer_v1.py']=orig_hash
   mod.footer_test=orig_footer_test

if __name__=='__main__':run()
