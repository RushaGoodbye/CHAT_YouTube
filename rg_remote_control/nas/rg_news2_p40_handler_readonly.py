#!/usr/bin/env python3
"""RG NEWS 2.0 P40 - guarded read-only moderation handler inspection.
Print only process_callback function from NAS. No API, no DB updates, no
token access, no cron edits, no secrets printed.
"""
import ast,datetime,hashlib,json,os,pathlib,re,sqlite3,sys
B=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
P=B/'rg_moderation.py'
D=B/'news.sqlite3'
def emit(**k):print(json.dumps(k,ensure_ascii=False,indent=2,sort_keys=True),flush=True)
def main():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 if not P.is_file() or P.is_symlink():raise RuntimeError('MODERATION_SOURCE_MISSING')
 source=P.read_text('utf-8')
 tree=ast.parse(source)
 nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=='process_callback']
 if len(nodes)!=1:raise RuntimeError('HANDLER_NOT_UNIQUE')
 n=nodes[0];lines=source.splitlines()
 body='\n'.join(f'{i+1}: {lines[i]}' for i in range(n.lineno-1,n.end_lineno))
 # Handler is Python logic, but refuse to print if any literal looks like a
 # long credential, secret or bot URL.
 credential_terms=('api.telegram.org/bot','bearer ','bot_token','secret_key','api_key','password')
 if any(t in body.lower() for t in credential_terms):
  raise RuntimeError('SOURCE_CONTAINS_SENSITIVE_LITERAL_REFUSED')
 if len(body)>16000:raise RuntimeError('HANDLER_TOO_LARGE')
 cols={}
 if D.is_file():
  db=sqlite3.connect('file:'+str(D)+'?mode=ro',uri=True,timeout=5)
  try:
   for table in ('candidates','moderation_dispatch'):
    cols[table]=[row[1] for row in db.execute('PRAGMA table_info('+table+')')]
  finally:db.close()
 emit(status='NEWS2_P40_ACTUAL_HANDLER_READONLY',timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
   source_sha256=hashlib.sha256(source.encode('utf-8')).hexdigest(),
   handler_source=body,database_column_names=cols,
   telegram_calls=0,files_modified=0,db_modified=0,publication_sends=0)
if __name__=='__main__':
 try:main()
 except Exception as e:
  emit(status='NEWS2_P40_BLOCKED',reason=str(e) if isinstance(e,RuntimeError) else type(e).__name__,
    telegram_calls=0,files_modified=0,db_modified=0,publication_sends=0);sys.exit(1)
