#!/usr/bin/env python3
"""NEWS2 remove redundant CTA in root composer and canonical final footer.
Offline-only. Safe backups and rollback; no Telegram calls.
"""
import ast,datetime as dt,hashlib,json,os,pathlib,re,subprocess,sys,tempfile
BASE=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
ROOT=BASE/'news_rg_organic_post_v1.py'
FOOT=BASE/'operator/news_rg_project_footer_v1.py'
CTA="📲 Більше новин і відео — у РАША ГУДБАЙ."
LINE=" if digest%3==1:additions.append("+repr(CTA)+")\n"
# Actual source uses single quoted Python string and matches repr(CTA).
REMOVE=" # Promotional CTA removed: canonical project-links footer is appended separately.\n"
EXTRA_OLD='  "Більше новин і відео → РАША ГУДБАЙ.",\n'
EXTRA_NEW='  "Більше новин і відео → РАША ГУДБАЙ.",\n  "📲 Більше новин і відео — у РАША ГУДБАЙ.",\n  "Більше новин і відео — у РАША ГУДБАЙ.",\n'
# Normalize only standalone legacy CTA lines, not news content and not links.
INSERT_AFTER=' lines=[line for line in lines if line.strip() not in old_set]\n'
REGEX=' lines=[line for line in lines if not re.fullmatch(r"(?:📲\\s*)?Більше\\s+новин\\s+і\\s+відео\\s*(?:→|—|-)\\s*(?:у\\s+)?РАША\\s+ГУДБАЙ\\.?",line.strip(),flags=re.I)]\n'
TEST_ANCHOR=' assert clean_legacy("Заголовок.\\n\\nБільше новин і відео → РАША ГУДБАЙ.\\n\\nДеталі.")=="Заголовок.\\n\\nДеталі."\n'
NEWTEST=' assert clean_legacy("Заголовок.\\n\\n📲 Більше новин і відео — у РАША ГУДБАЙ.\\n\\nДеталі.")=="Заголовок.\\n\\nДеталі."\n'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def require(b,msg):
 if not b:raise RuntimeError(msg)
def write(p, data):
 fd,tmp=tempfile.mkstemp(prefix='.cta_fix_',dir=p.parent)
 try:
  os.fchmod(fd,p.stat().st_mode&0o777)
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def run():
 for p in (ROOT,FOOT):require(p.is_file() and not p.is_symlink(),'MISSING_OR_LINK_'+p.name)
 root=ROOT.read_text('utf8');foot=FOOT.read_text('utf8')
 require(root.count(LINE)==1,'ROOT_COMPOSER_ANCHOR_CHANGED')
 require(foot.count(EXTRA_OLD)==1 and foot.count(INSERT_AFTER)==1,'FOOTER_ANCHOR_CHANGED')
 target_root=root.replace(LINE,REMOVE,1)
 target_foot=foot.replace(EXTRA_OLD,EXTRA_NEW,1).replace(INSERT_AFTER,INSERT_AFTER+REGEX,1)
 require(NEWTEST not in target_foot,'ALREADY_TESTED')
 require(' assert clean_legacy("Заголовок.' in foot,'FOOTER_SELFTEST_NOT_FOUND')
 # Insert test with a stable single-line anchor based on search.
 anchor=' assert clean_legacy("Заголовок.\\n\\nБільше новин і відео → РАША ГУДБАЙ.\\n\\nДеталі.")=="Заголовок.\\n\\nДеталі."\n'
 # The source contains escaped newlines; Python string above is literal backslash-n.
 require(target_foot.count(anchor)==1,'FOOTER_SELFTEST_ANCHOR_CHANGED')
 target_foot=target_foot.replace(anchor,anchor+NEWTEST,1)
 # Expand sample loop to ensure regression detection.
 loop='    "💥 Новина\\n\\nУСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ РАША ГУДБАЙ",'
 require(loop in target_foot,'FOOTER_SAMPLE_LOOP_CHANGED')
 target_foot=target_foot.replace(loop,'    "💥 Новина\\n\\n📲 Більше новин і відео — у РАША ГУДБАЙ.",\n'+loop,1)
 require('Більше новин і відео' not in target_root or "if FOOTER in s or '📲 Більше новин і відео' in s" in target_root,'ROOT_LAYOUT_CHANGED')
 for p,body in ((ROOT,target_root),(FOOT,target_foot)):ast.parse(body,filename=str(p))
 ret={'status':'CTA_PATCH_PRECHECK_PASS','root_before_sha256':digest(ROOT),'footer_before_sha256':digest(FOOT),
 'modified_sources':[str(ROOT),str(FOOT)],'telegram_calls':0,'publications':0}
 if '--apply' not in sys.argv:
  print(json.dumps(ret,ensure_ascii=False));return
 require(os.geteuid()==0,'SUDO_REQUIRED')
 backup=BASE/'operator'/'news_rg_cta_fix_backups'
 require(not backup.is_symlink(),'BACKUP_SYMLINK')
 backup.mkdir(parents=True,exist_ok=True,mode=0o700)
 stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 saved={}
 for p in (ROOT,FOOT):
  path=backup/(p.name+'.'+stamp+'.bak')
  require(not path.exists(),'BACKUP_COLLISION')
  data=p.read_bytes();path.write_bytes(data);os.chmod(path,0o600)
  saved[p]=data
 modified=[]
 try:
  for p,b in ((ROOT,target_root),(FOOT,target_foot)):
   write(p,b.encode('utf8'));modified.append(p)
  python=sys.executable
  for p,expected in ((ROOT,'RG_ORGANIC_COMPOSER_SELFTEST_PASS'),(FOOT,'NEWS_RG_CANONICAL_FOOTER_SELFTEST_PASS')):
   cp=subprocess.run([python,str(p)],capture_output=True,text=True,timeout=25)
   require(cp.returncode==0 and expected in cp.stdout,'SELFTEST_FAILED_'+p.name+':'+cp.stderr[-400:])
  # Source guard for both routes, plus preserved footer URL.
  require(CTA not in ROOT.read_text('utf8'),'COMPOSER_CTA_STILL_PRESENT')
  require('https://links.rginfoua.pp.ua/' in FOOT.read_text('utf8'),'CANONICAL_FOOTER_URL_MISSING')
  ret['status']='REDUNDANT_CTA_REMOVED_TESTS_PASS'
  ret['backup_files']=[str(backup/(p.name+'.'+stamp+'.bak')) for p in saved]
  ret['root_after_sha256']=digest(ROOT);ret['footer_after_sha256']=digest(FOOT)
  print(json.dumps(ret,ensure_ascii=False,indent=2))
 except Exception:
  for p in reversed(modified):write(p,saved[p])
  raise
if __name__=='__main__':
 try:run()
 except Exception as exc:
  print(json.dumps({'status':'SAFE_STOP','reason':str(exc)[:350],'telegram_calls':0,'publications':0},ensure_ascii=False))
  sys.exit(2)
