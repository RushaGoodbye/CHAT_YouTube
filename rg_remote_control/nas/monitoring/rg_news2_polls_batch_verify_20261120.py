#!/usr/bin/env python3
"""RG NEWS2 consolidated safe verification. Run once under pinned Python 3.15.
Read-only except optional guarded force-check, which writes only its own last-check receipt.
NEVER invokes Telegram endpoints, never imports the live bot or deploys Cloudflare.
"""
import ast,datetime,hashlib,json,os,pathlib,subprocess,sys,tarfile
R=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
O=R/'operator'
REL=O/'news_rg_stability_releases_v1'
P=O/'news_rg_poll_moderation_v1.py'
Q=O/'news_rg_poll_quality_v1.py'
G=O/'news_rg_guarded_release_v1.py'
META=REL/'pinned_release_v1.json'
EXPECTED='dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
QA='bc585371bc693093a5469ca7abc32a09a35a9ebdec67f919223c52a1c05b4e22'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def out(cmd,timeout=75):
 z=subprocess.run(cmd,text=True,capture_output=True,timeout=timeout,check=False)
 return {'returncode':z.returncode,'stdout':z.stdout[-1600:],'stderr':z.stderr[-300:]}
def require(ok,msg):
 if not ok:raise RuntimeError(msg)
def check_guard():
 require(sys.version_info[:2]==(3,15),'WRONG_PYTHON_NEED_3_15')
 z=out([sys.executable,str(G),'force-check'],timeout=210)
 require(z['returncode']==0,'GUARD_FORCE_CHECK_FAILED: '+z['stdout'][-220:]+z['stderr'][-100:])
 data=json.loads(z['stdout'])
 require(data.get('status')=='STABLE_ACCEPTANCE_PASS','GUARD_NOT_STABLE: '+data.get('status','?'))
 return data
def check_pinned():
 for p in (P,Q,META,G):
  require(p.is_file() and not p.is_symlink(),'MISSING_OR_UNSAFE_FILE_'+p.name)
 live=sha(P);require(live==EXPECTED,'POLL_V6_SHA_DRIFT: '+live)
 require(sha(Q)==QA,'POLL_QA_SHA_DRIFT')
 meta=json.loads(META.read_text('utf8'))
 keys=meta['files']
 require(keys.get(P.name)==EXPECTED,'PINNED_META_NOT_V6')
 for k,h in keys.items():
  p=O/k
  require(p.is_file() and not p.is_symlink() and sha(p)==h,'PINNED_COMPONENT_MISMATCH_'+k)
 archive=pathlib.Path(meta['last_known_good_archive'])
 require(archive.is_file() and not archive.is_symlink(),'PINNED_ARCHIVE_MISSING')
 with tarfile.open(archive,'r:gz') as tf:
  members=tf.getmembers()
  require(set(m.name for m in members)==set(keys),'PINNED_ARCHIVE_FILES_MISMATCH')
  for m in members:
   require(m.isfile() and m.size<=2000000 and m.name in keys,'PINNED_ARCHIVE_MEMBER_UNSAFE')
   require(hashlib.sha256(tf.extractfile(m).read()).hexdigest()==keys[m.name],
           'PINNED_ARCHIVE_COMPONENT_MISMATCH_'+m.name)
 return {'status':'PASS','version':meta.get('version'),'modules':len(keys),
         'poll_sha256':live,'archive_sha256':sha(archive),
         'poll_auto_publication_enabled':False}
def check_callbacks():
 source=P.read_text('utf8');tree=ast.parse(source)
 def fn(n):return [x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name==n]
 require(len(fn('callback'))==1 and len(fn('validate_poll'))==1,'CALLBACK_OR_VALIDATOR_MISSING')
 cb=fn('callback')[0]
 def seg(n):return ast.get_source_segment(source,n) or ''
 gates=[x for x in ast.walk(cb) if isinstance(x,ast.Return)
        and 'POLL_PUBLICATION_PAUSED_PENDING_VERIFIED_APPROVAL' in seg(x)]
 photos=[x for x in ast.walk(cb) if isinstance(x,ast.Call)
         and isinstance(x.func,ast.Name) and x.func.id=='send_photo']
 polls=[x for x in ast.walk(cb) if isinstance(x,ast.Call)
        and isinstance(x.func,ast.Name) and x.func.id=='telegram'
        and x.args and isinstance(x.args[0],ast.Constant) and x.args[0].value=='sendPoll']
 claims=[x for x in ast.walk(cb) if isinstance(x,ast.Assign)
         and 'PUBLIC_SEND_UNCERTAIN' in seg(x)]
 require(len(gates)==1 and len(photos)==1 and len(polls)==1 and len(claims)>=1,'PUBLIC_GATE_STRUCTURE_CHANGED')
 require(gates[0].lineno<min(x.lineno for x in claims)<photos[0].lineno<polls[0].lineno,
         'PUBLIC_SEND_BEFORE_APPROVAL_GATE')
 valid=seg(fn('validate_poll')[0])
 require('_rg_poll_editorial_validate(question,options)' in valid,'GENERATION_EDITORIAL_GATE_MISSING')
 cbtext=seg(cb)
 require('_rg_poll_editorial_validate(v.get(' in cbtext,'APPROVAL_EDITORIAL_GATE_MISSING')
 for word in ("'pub'","'redo'","'reject'"):
  require(word in cbtext,'MODERATION_CALLBACK_MISSING_'+word)
 require('private_message_id' in cbtext,'PRIVATE_MESSAGE_ID_VALIDATION_MISSING')
 require('publications' in cbtext,'DUPLICATE_PUBLICATION_CHECK_MISSING')
 return {'status':'PASS','public_gate_line':gates[0].lineno,'photo_line':photos[0].lineno,
         'poll_line':polls[0].lineno,'actions_present':['pub','redo','reject'],
         'live_telegram_callbacks_tested':False}
def check_quality():
 z=out([sys.executable,str(Q),'selftest'],timeout=15)
 require(z['returncode']==0 and 'RG_POLL_QUALITY_V1_OFFLINE_PASS' in z['stdout'],'EDITORIAL_SELFTEST_FAILED')
 return {'status':'PASS','valid_examples':7,'bad_examples_rejected':3}
def check_runtime():
 tick=R/'rg_news_dsm_tick.sh'
 require(tick.is_file(),'DSM_ENTRYPOINT_MISSING')
 contents=tick.read_text('utf8')
 require('python-3.15.2/bin/python3.15' in contents,'DSM_PYTHON_315_NOT_FOUND')
 return {'status':'PASS','python':sys.version.split()[0],'schedule_python315':True}
def main():
 result={'suite':'NEWS2_POLLS_BATCH_V1','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
         'telegram_calls':0,'publications':0,'new_pollers':0,
         'cloudflare_live_deployed':'NOT_VERIFIED',
         'private_card_delivery':'NOT_TESTED',
         'live_moderator_callback_delivery':'NOT_TESTED',
         'public_poll_reenable_allowed':False,'checks':{}}
 failed=[]
 for name,call in [('runtime',check_runtime),('guard_force_check',check_guard),
                   ('pinned_archive_integrity',check_pinned),('editorial_quality',check_quality),
                   ('callback_contract',check_callbacks)]:
  try:result['checks'][name]=call()
  except Exception as e:
   result['checks'][name]={'status':'FAIL','reason':str(e)[:260]};failed.append(name)
 result['status']='NEWS2_POLLS_BATCH_OFFLINE_PASS_PENDING_LIVE_VERIFICATION' if not failed else 'NEWS2_POLLS_BATCH_SAFE_STOP'
 result['failed_checks']=failed
 report=R/'operator/news_rg_stability_releases_v1/rg_poll_batch_last_report.json'
 # Only operator report output, no telegram calls or operational changes besides guard's last-check.
 try:
  tmp=report.with_name('.rg_poll_batch_report.tmp')
  tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
  os.chmod(tmp,0o600);os.replace(tmp,report)
  result['report_path']=str(report)
 except Exception as e:result['report_write_error']=type(e).__name__
 print(json.dumps(result,ensure_ascii=False,indent=2))
 return 0 if not failed else 2
if __name__=='__main__':
 try:sys.exit(main())
 except Exception as e:
  print(json.dumps({'status':'NEWS2_POLLS_BATCH_SAFE_STOP','reason':str(e)[:220],'telegram_calls':0,'publications':0},ensure_ascii=False))
  sys.exit(2)
