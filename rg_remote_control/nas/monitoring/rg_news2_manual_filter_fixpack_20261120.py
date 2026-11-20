#!/usr/bin/env python3
"""NEWS2 one-shot guarded prepatch: evidence + backup, without unsafe blind edits."""
import ast,datetime,hashlib,json,os,pathlib,re,sys,tarfile
ROOT=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2');OP=ROOT/'operator'
PIN=OP/'news_rg_stability_releases_v1/pinned_release_v1.json'
GUARD=OP/'news_rg_poll_moderation_v1.py'
SHA='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
PAT=re.compile(r'(?i)(сатир|мем|satire|meme|parody|front|обов.язков.{0,25}випуск|manual.{0,10}source|source.{0,10}link)')
SECRET=re.compile(r'(?i)(token|secret|password|authorization|api.key|chat_id|user_id|https?://|bot[0-9]{7,}:)')
def main():
 manifest=json.loads(PIN.read_text('utf8'))
 if (not isinstance(manifest.get('files'),dict) or GUARD.is_symlink()
   or hashlib.sha256(GUARD.read_bytes()).hexdigest()!=SHA
   or manifest['files'].get(GUARD.name)!=SHA):raise RuntimeError('V6_INTEGRITY_FAILURE')
 pinned={pathlib.Path(k).name for k in manifest['files']}
 matches=[];files=set()
 for folder in (ROOT,OP):
  for p in folder.iterdir():
   if p.suffix not in ('.py','.js','.sh','.json') or p.is_symlink() or not p.is_file():continue
   if p in files or p.stat().st_size>300000:continue
   files.add(p)
   try:source=p.read_text('utf8')
   except (OSError,UnicodeError):continue
   lines=source.splitlines()
   locations=[i for i,s in enumerate(lines) if PAT.search(s)]
   if not locations:continue
   funcs=[]
   if p.suffix=='.py':
    try:
     tree=ast.parse(source)
     funcs=[(x.lineno,x.end_lineno,x.name) for x in ast.walk(tree)
       if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef))]
    except SyntaxError:pass
   samples=[]
   for i in locations[:12]:
    fs=[x for x in funcs if x[0]<=i+1<=x[1]]
    f=min(fs,key=lambda x:x[1]-x[0])[2] if fs else 'module'
    near=[]
    for j in range(max(0,i-1),min(len(lines),i+2)):
     t=lines[j].strip()
     near.append({'line':j+1,'source':'[REDACTED]' if SECRET.search(t) else t[:180]})
    samples.append({'line':i+1,'function':f,'near':near})
   matches.append({'file':str(p.relative_to(ROOT)),'pinned':p.name in pinned,
     'hits':len(locations),'samples':samples})
 dest=OP/'news_rg_stability_releases_v1/manual_intake_repair_backups'
 if dest.is_symlink():raise RuntimeError('UNSAFE_BACKUP_DIRECTORY')
 dest.mkdir(mode=0o700,parents=True,exist_ok=True)
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 archive=dest/('prepatch_'+stamp+'.tar.gz')
 if archive.exists():raise RuntimeError('BACKUP_EXISTS')
 with tarfile.open(archive,'x:gz') as z:
  for item in matches:z.add(ROOT/item['file'],arcname=item['file'],recursive=False)
 os.chmod(archive,0o600)
 print(json.dumps({'status':'SOURCE_IDENTIFIED_PATCH_PENDING_SAFE_REVIEW',
  'matched_modules':len(matches),
  'candidate_code':sorted(matches,key=lambda x:-x['hits'])[:30],
  'backup':archive.name,
  'manual_post':'https://t.me/polit1humor/14293',
  'required_behavior':{'satire':'WARN_AND_SEND_TO_PRIVATE_REVIEW',
     'front_unavailable':'WARN_SEPARATELY_DO_NOT_BLOCK_MANUAL_REVIEW',
     'duplicate':'DEDUPLICATE_BY_SOURCE_ID'},
  'v6':'PASS','files_modified':0,'publications':0,'getUpdates_calls':0},ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','error':type(e).__name__,'files_modified':0,'publications':0}))
  sys.exit(2)
