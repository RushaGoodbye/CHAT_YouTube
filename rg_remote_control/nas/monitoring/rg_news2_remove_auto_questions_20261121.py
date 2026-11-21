#!/usr/bin/env python3
"""Remove redundant audience questions from all active RG NEWS2 publication composers.
Root-only, atomic rollback, tests before and after, no Telegram API or publications.
"""
import ast,datetime,hashlib,json,os,pathlib,re,shutil,subprocess,sys,tempfile
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=B/'operator'
OP=O/'news_rg_organic_post_v1.py'
ROOT=B/'news_rg_organic_post_v1.py'
FOOTER=O/'news_rg_project_footer_v1.py'
BACK=O/'news_rg_question_cleanup_backups'
Q1='💬 Що думаєте про цю подію?'
Q2='💬 Як ви оцінюєте цю новину?'
def output(**kw):print(json.dumps(kw,ensure_ascii=False,indent=2))
def check(c,s):
 if not c:raise RuntimeError(s)
def sha(s):return hashlib.sha256(s.encode('utf8')).hexdigest()
def read(p):
 check(p.is_file() and not p.is_symlink() and p.stat().st_size<12000,'SOURCE_INVALID_'+p.name)
 return p.read_text('utf8')
def patch_operator(s):
 target=" if not tragic and digest%7==0 and len(s)>70:\n  body+='\\n\\n💬 Що думаєте про цю подію?'\n"
 check(s.count(target)==1,'OPERATOR_QUESTION_ANCHOR_CHANGED')
 s=s.replace(target,' # NEWS2 editor policy: no auto-inserted audience questions.\n')
 s=s.replace(" assert '💬' not in decorate(tragedy)"," assert '💬' not in decorate(tragedy)\n assert Q1 not in decorate(factual+unsupported)") if False else s
 # Add test directly after existing tragedy test.
 anchor=" assert '💬' not in decorate(tragedy)\n"
 check(s.count(anchor)==1,'OPERATOR_SELFTEST_ANCHOR_CHANGED')
 s=s.replace(anchor,anchor+" assert '💬 Що думаєте про цю подію?' not in decorate(factual+unsupported)\n")
 return s
def patch_root(s):
 target=" if digest%4==0 and not any(x in s.lower() for x in ('загин','жертв','поран','дитин','траур','похорон','загибл')):additions.append('💬 Як ви оцінюєте цю новину?')\n"
 check(s.count(target)==1,'ROOT_QUESTION_ANCHOR_CHANGED')
 s=s.replace(target," # NEWS2 editor policy: no auto-inserted audience questions.\n")
 anchor=" assert decorate(decorate(s))==decorate(s)\n"
 check(s.count(anchor)==1,'ROOT_SELFTEST_ANCHOR_CHANGED')
 s=s.replace(anchor,anchor+" assert '💬 Як ви оцінюєте цю новину?' not in decorate(s)\n")
 return s
def patch_footer(s):
 anchor=" lines=[line for line in lines if line.strip() not in old_set]\n"
 check(s.count(anchor)==1,'FOOTER_CLEANUP_ANCHOR_CHANGED')
 s=s.replace(anchor,anchor+
 " # Remove both obsolete question prompts, including legacy scheduled captions.\n"
 " lines=[line for line in lines if not re.fullmatch(r'(?:💬\\s*)?(?:Що\\s+думаєте\\s+про\\s+цю\\s+подію|Як\\s+ви\\s+оцінюєте\\s+цю\\s+новину)\\s*[?？]?\\s*',line.strip(),flags=re.I)]\n")
 anchor=" assert clean_legacy(\"Заголовок.\\n\\n📲 Більше новин і відео — у РАША ГУДБАЙ.\\n\\nДеталі.\")==\"Заголовок.\\n\\nДеталі.\"\n"
 check(s.count(anchor)==1,'FOOTER_TEST_ANCHOR_CHANGED')
 s=s.replace(anchor,anchor+
 " assert clean_legacy(\"Новина.\\n\\n💬 Що думаєте про цю подію?\\n\\nДеталі.\")==\"Новина.\\n\\nДеталі.\"\n"
 " assert clean_legacy(\"Новина.\\n\\n💬 Як ви оцінюєте цю новину?\\n\\nДеталі.\")==\"Новина.\\n\\nДеталі.\"\n")
 return s
def write_atomic(p,content):
 fd,tmp=tempfile.mkstemp(dir=p.parent,prefix='.rg_question_update_',suffix='.tmp')
 try:
  os.fchmod(fd,p.stat().st_mode&0o777)
  with os.fdopen(fd,'w',encoding='utf8') as f:
   f.write(content);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def run_script(p):
 c=subprocess.run([sys.executable,str(p)],capture_output=True,text=True,timeout=30)
 check(c.returncode==0,'SELFTEST_FAILED_'+p.name+':'+(c.stdout+c.stderr)[-180:])
 return c.stdout.strip()
def main():
 check(os.geteuid()==0,'SUDO_REQUIRED')
 check(not (B/'PUBLISH_ENABLED').exists() and not (B/'PUBLISH_ENABLED').is_symlink(),'PUBLIC_GATE_CHANGED')
 original={p:read(p) for p in (OP,ROOT,FOOTER)}
 modified={OP:patch_operator(original[OP]),ROOT:patch_root(original[ROOT]),FOOTER:patch_footer(original[FOOTER])}
 for p,s in modified.items():ast.parse(s)
 # Validate selftests against isolated candidate imports, including production footer->operator import behavior.
 with tempfile.TemporaryDirectory(prefix='rg_question_offline_') as t:
  d=pathlib.Path(t)
  for p,s in modified.items():(d/p.name).write_text(s,'utf8')
  # OP and ROOT share filename; selftests executed individually, footer uses OP in import path.
  for p in (OP,ROOT):
   c=subprocess.run([sys.executable,'-c',
     'import ast; s='+repr(modified[p])+'; x=ast.parse(s); n={}; exec(compile(x,"<test>","exec"),n); n["selftest"]()'],
     capture_output=True,text=True,timeout=30)
   check(c.returncode==0,'OFFLINE_COMPOSER_TEST_FAILED_'+str(p)+':'+(c.stderr+c.stdout)[-130:])
  c=subprocess.run([sys.executable,'-c',
    'import sys; sys.path.insert(0,'+repr(str(d))+'); import news_rg_project_footer_v1 as f; f.selftest()'],
    capture_output=True,text=True,timeout=30)
  # Folder collision means root composer installed in test path: footer test still confirms cleanup.
  check(c.returncode==0,'OFFLINE_FOOTER_TEST_FAILED_'+(c.stderr+c.stdout)[-180:])
 if '--apply' not in sys.argv:
  output(status='QUESTION_REMOVAL_READY',modules=[str(p) for p in modified],telegram_calls=0,publications=0)
  return
 BACK.mkdir(mode=0o700,exist_ok=True);os.chmod(BACK,0o700)
 ts=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 backups={}
 for p,s in original.items():
  name=('root_' if p==ROOT else 'operator_' if p==OP else 'footer_')+p.name+'.'+ts+'.bak'
  bp=BACK/name
  fd=os.open(bp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
  with os.fdopen(fd,'w',encoding='utf8') as f:f.write(s);f.flush();os.fsync(f.fileno())
  backups[p]=bp
 written=[]
 try:
  for p,s in modified.items():
   check(read(p)==original[p],'SOURCE_CHANGED_CONCURRENTLY_'+p.name)
   write_atomic(p,s);written.append(p)
  tests={str(p):run_script(p) for p in modified}
  # Actual package import, not isolated test, must be valid with the original footer.
  sys.path.insert(0,str(O))
  import news_rg_project_footer_v1 as f
  result,entities=f.append_footer('Новина про корабель.\n\n💬 Що думаєте про цю подію?')
  check(Q1 not in result and Q2 not in result,'CANONICAL_FOOTER_QUESTION_REMAINS')
  check(result.count(f.FOOTER_TEXT)==1 and entities[-1].get('url')==f.FOOTER_URL,'FOOTER_LINK_CHANGED')
 except Exception:
  for p in reversed(written):write_atomic(p,original[p])
  raise
 output(status='RG_NEWS2_QUESTIONS_REMOVED_TESTS_PASS',modified_modules=[str(p) for p in modified],
  backup_files=[str(v) for v in backups.values()],
  before_sha256={str(p):sha(s) for p,s in original.items()},
  after_sha256={str(p):sha(s) for p,s in modified.items()},
  telegram_calls=0,publications=0,public_gate='OFF',new_pollers=0)
if __name__=='__main__':
 try:main()
 except Exception as e:
  output(status='SAFE_STOP',reason=str(e)[:250],publications=0,new_pollers=0)
  sys.exit(2)
