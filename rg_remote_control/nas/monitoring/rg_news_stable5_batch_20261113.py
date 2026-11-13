#!/usr/bin/env python3
"""Promote a previously tested Stable5 healthcheck fix. No Telegram API calls."""
from pathlib import Path
import ast, hashlib, importlib.util, json, os, shutil, sys
O=Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
R=O/'news_rg_stability_releases_v1'
G=O/'news_rg_guarded_release_v1.py'
T=O/'news_rg_stable5_operational_gate_v1.py'
M=R/'pinned_release_v1.json'
NEW='if p.returncode not in (0,1,2) or not p.stdout.strip():'
OLD='if p.returncode not in (0,1) or not p.stdout.strip():'
staged=[]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def need(ok,msg):
 if not ok: raise RuntimeError('SAFE_STOP_'+msg)
def main():
 need(os.geteuid()==0,'ROOT')
 need(sys.version_info[:3]==(3,15,2),'PYTHON')
 need(all(p.is_file() and not p.is_symlink() for p in (G,T,M)),'FILES')
 tree=ast.parse(G.read_text())
 assign=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='KEY' for t in n.targets))
 keys=ast.literal_eval(assign.value)
 need(isinstance(keys,tuple) and len(keys)==17 and T.name in keys,'KEYS')
 need(all(isinstance(k,str) and '/' not in k and '\\' not in k for k in keys),'KEY_NAMES')
 meta=json.loads(M.read_text())
 need(meta.get('acceptance')=='PASS' and str(meta.get('version','')).startswith('2026-11-05-stable'),'RELEASE')
 archive=Path(meta.get('last_known_good_archive','/missing'))
 need(archive.is_file(),'ARCHIVE')
 expected=meta.get('files') or {}
 need(set(expected)==set(keys),'MANIFEST')
 for k in keys:
  p=O/k
  need(p.is_file() and not p.is_symlink(),'FILE_'+k)
  if p!=T: need(sha(p)==expected[k],'DRIFT_'+k)
 code=T.read_text()
 need(code.count(NEW)==1 and OLD not in code,'PATCH_MISSING')
 need(sha(T)!=expected[T.name],'ALREADY_PINNED')
 need(all(not (O/('.'+k+'.stability_candidate')).exists() for k in keys),'EXISTING_STAGING')
 guard=G.read_text()
 need(all(s in guard for s in ('def acceptance(', 'def install(', 'restore(prior)', 'automatic_publication_disabled_during_tests')),'GUARD_CONTRACT')
 print('PREFLIGHT_PASS components=17',flush=True)
 for k in keys:
  source=O/k
  candidate=O/('.'+k+'.stability_candidate')
  with open(source,'rb') as inp, open(candidate,'xb') as out:
   shutil.copyfileobj(inp,out)
   out.flush();os.fsync(out.fileno())
  os.chmod(candidate,source.stat().st_mode & 0o777)
  staged.append(candidate)
 spec=importlib.util.spec_from_file_location('rg_stable_guard',G)
 module=importlib.util.module_from_spec(spec)
 spec.loader.exec_module(module)
 module.install()
 final=json.loads(M.read_text())
 need(final.get('acceptance')=='PASS','FINAL_ACCEPTANCE')
 need(sha(T)==final['files'][T.name] and NEW in T.read_text(),'FINAL_HASH')
 need(Path(final['last_known_good_archive']).is_file(),'FINAL_ARCHIVE')
 print('BATCH_RELEASE_PASS',flush=True)
 print('PINNED_SHA256',sha(T),flush=True)
 print('OLD_ARCHIVE_PRESERVED',archive.exists(),flush=True)
if __name__=='__main__':
 try: main()
 except Exception as e:
  print('BATCH_SAFE_STOP',type(e).__name__,str(e)[:200],flush=True)
  sys.exit(1)
 finally:
  for p in staged:
   try: p.unlink(missing_ok=True)
   except OSError: pass
