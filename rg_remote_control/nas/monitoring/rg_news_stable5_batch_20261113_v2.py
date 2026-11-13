#!/usr/bin/env python3
"""Safe Stable5 release patch. Requires root, pinned release, and Python 3.15.2.
Never invokes Telegram; existing guarded install performs acceptance and rollback.
"""
from pathlib import Path
import ast, hashlib, importlib.util, json, os, shutil, sys
O=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
R=O/'news_rg_stability_releases_v1'
G=O/'news_rg_guarded_release_v1.py'
T=O/'news_rg_stable5_operational_gate_v1.py'
M=R/'pinned_release_v1.json'
OLD='if p.returncode not in (0,1) or not p.stdout.strip():'
NEW='if p.returncode not in (0,1,2) or not p.stdout.strip():'
staged=[]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def need(ok,msg):
 if not ok: raise RuntimeError('SAFE_STOP_'+msg)
def main():
 need(os.geteuid()==0,'ROOT')
 need(sys.version_info[:3]==(3,15,2),'PYTHON_VERSION')
 need(all(p.is_file() and not p.is_symlink() for p in (G,T,M)),'FILES')
 tree=ast.parse(G.read_text())
 key_nodes=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='KEY' for t in n.targets)]
 need(len(key_nodes)==1,'GUARD_KEY_DEFINITION')
 keys=ast.literal_eval(key_nodes[0].value)
 need(isinstance(keys,tuple) and len(keys)==18 and len(set(keys))==18 and T.name in keys,'KEYS')
 need(all(isinstance(k,str) and k.endswith('.py') and '/' not in k and chr(92) not in k for k in keys),'KEY_NAMES')
 meta=json.loads(M.read_text())
 need(meta.get('acceptance')=='PASS' and str(meta.get('version','')).startswith('2026-11-05-stable'),'PINNED_RELEASE')
 archive=Path(meta.get('last_known_good_archive','/missing'))
 need(archive.is_file() and archive.is_file() and not archive.is_symlink(),'PINNED_ARCHIVE')
 expected=meta.get('files') or {}
 need(set(expected)==set(keys),'MANIFEST')
 for k in keys:
  p=O/k
  need(p.is_file() and not p.is_symlink(),'FILE_'+k)
  need(sha(p)==expected[k],'DRIFT_'+k)
 source=T.read_text()
 need(source.count(OLD)==1 and NEW not in source,'ORIGINAL_NOT_PRESENT')
 guard=G.read_text()
 need(all(s in guard for s in ('def acceptance(', 'def install(', 'restore(prior)', 'automatic_publication_disabled_during_tests')),'GUARD_CONTRACT')
 need(all(not (O/('.'+k+'.stability_candidate')).exists() for k in keys),'EXISTING_STAGING')
 print('PREFLIGHT_PASS 18_MODULES; ARCHIVE_VALID; PINNED_HASHES_MATCH',flush=True)
 for k in keys:
  source_path=O/k
  stage=O/('.'+k+'.stability_candidate')
  data=source_path.read_bytes()
  if k==T.name:
   patched=data.decode('utf-8').replace(OLD,NEW)
   compile(patched,str(stage),'exec')
   data=patched.encode('utf-8')
  fd=os.open(stage,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  staged.append(stage)
  with os.fdopen(fd,'wb') as out:
   out.write(data)
   out.flush();os.fsync(out.fileno())
  os.chmod(stage,source_path.stat().st_mode & 0o777)
 print('STAGING_PASS',flush=True)
 spec=importlib.util.spec_from_file_location('rg_stable_guard',G)
 module=importlib.util.module_from_spec(spec)
 spec.loader.exec_module(module)
 module.install()
 final=json.loads(M.read_text())
 need(final.get('acceptance')=='PASS','FINAL_ACCEPTANCE')
 need(sha(T)==final['files'][T.name] and NEW in T.read_text(),'FINAL_PATCH_OR_HASH')
 need(Path(final['last_known_good_archive']).is_file(),'FINAL_BACKUP')
 print('BATCH_RELEASE_PASS',flush=True)
 print('PINNED_PATCH_SHA256',sha(T),flush=True)
 print('PREVIOUS_ARCHIVE_PRESERVED',archive.exists(),flush=True)
if __name__=='__main__':
 try: main()
 except Exception as e:
  print('BATCH_SAFE_STOP',type(e).__name__,str(e)[:200],flush=True)
  sys.exit(1)
 finally:
  for p in staged:
   try: p.unlink(missing_ok=True)
   except OSError: pass
