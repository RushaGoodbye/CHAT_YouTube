#!/usr/bin/env python3
"""NEWS RG dedicated health -> existing Gatus external endpoint. No Telegram.

Run only from existing rg_news_dsm_tick.sh. Uses a local root-only token file.
Never runs AI, Telegram API, pollers or publication. Calls READ-ONLY monitor.
"""
import sys,os,json,pathlib,subprocess,urllib.request,urllib.parse,urllib.error,time,tempfile,re
OP=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2/operator')
HEALTH=OP/'news_rg_stability_healthcheck_v1.py'
TOKEN=OP/'news_rg_gatus_stability_token_v1'
LAST=OP/'news_rg_gatus_health_push_last_v1.json'
KEY='rg-nas_news-rg-stability'
URL='http://127.0.0.1:18080/api/v1/endpoints/'+KEY+'/external'
MARK='NEWS_RG_GATUS_STABILITY_PUSH_V1'
def safe_token():
 if TOKEN.is_symlink() or not TOKEN.is_file() or TOKEN.stat().st_size>150:raise RuntimeError('TOKEN_NOT_INSTALLED')
 if TOKEN.stat().st_mode & 0o077:raise RuntimeError('TOKEN_PERMISSIONS_UNSAFE')
 token=TOKEN.read_text('ascii').strip()
 if not re.fullmatch(r'[0-9a-f]{48}',token):raise RuntimeError('TOKEN_INVALID')
 return token
def health():
 if HEALTH.is_symlink() or not HEALTH.is_file():raise RuntimeError('HEALTHCHECK_MISSING')
 p=subprocess.run(['/usr/bin/python3',str(HEALTH),'check'],stdout=subprocess.PIPE,
   stderr=subprocess.DEVNULL,text=True,timeout=25)
 if p.returncode not in (0,1,2,3):raise RuntimeError('HEALTHCHECK_BAD_RC')
 d=json.loads(p.stdout)
 st=d.get('status')
 if st not in ('HEALTHY','WARNING','CRITICAL','UNKNOWN'):raise RuntimeError('HEALTHCHECK_BAD_STATUS')
 if d.get('read_only') is not True or d.get('telegram_calls')!=0 or d.get('publications_triggered')!=0:
  raise RuntimeError('HEALTHCHECK_SAFETY_CONTRACT_BROKEN')
 if {'HEALTHY':0,'WARNING':1,'CRITICAL':2,'UNKNOWN':3}[st]!=p.returncode:
  raise RuntimeError('HEALTHCHECK_STATUS_RC_MISMATCH')
 return st
def push(st,token):
 params={'success':'true' if st=='HEALTHY' else 'false'}
 if st!='HEALTHY':params['error']='NEWS_RG_'+st
 url=URL+'?'+urllib.parse.urlencode(params)
 req=urllib.request.Request(url,data=b'',method='POST',
    headers={'Authorization':'Bearer '+token,'User-Agent':'news-rg-stability/1'})
 with urllib.request.urlopen(req,timeout=8) as response:
  if response.status not in (200,201,202,204):raise RuntimeError('GATUS_ACK_INVALID')
 return True
def persist(status,health_status,ack):
 LAST.parent.mkdir(parents=False,exist_ok=True)
 content=json.dumps({'schema':MARK,'status':status,'health':health_status,
   'gatus_ack':ack,'checked_at':int(time.time())},sort_keys=True).encode()
 fd,name=tempfile.mkstemp(prefix='.news_rg_gatus_push_',dir=str(LAST.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchmod(f.fileno(),0o600);f.write(content);f.flush();os.fsync(f.fileno())
  os.replace(name,LAST)
 finally:
  if os.path.exists(name):os.unlink(name)
def run():
 if os.geteuid()!=0:raise RuntimeError('SUDO_REQUIRED')
 token=safe_token()
 st=health()
 try:
  push(st,token)
 except (urllib.error.URLError,OSError,RuntimeError):
  persist('GATUS_ACK_NOT_CONFIRMED',st,False)
  return {'status':'GATUS_ACK_NOT_CONFIRMED','health':st,'gatus_ack':False}
 persist('GATUS_PUSH_CONFIRMED',st,True)
 return {'status':'GATUS_PUSH_CONFIRMED','health':st,'gatus_ack':True,
  'endpoint_key':KEY}
def selftest():
 assert KEY=='rg-nas_news-rg-stability'
 assert URL.startswith('http://127.0.0.1:18080/')
 for st in ('HEALTHY','WARNING','CRITICAL','UNKNOWN'):
  params={'success':'true' if st=='HEALTHY' else 'false'}
  if st!='HEALTHY':params['error']='NEWS_RG_'+st
  u=URL+'?'+urllib.parse.urlencode(params)
  assert ('success=true' in u)==(st=='HEALTHY')
 assert re.fullmatch(r'[0-9a-f]{48}','a'*48)
 print('NEWS_RG_GATUS_HEALTH_PUSH_SELFTEST_PASS')
if __name__=='__main__':
 try:
  if sys.argv[1:]==['selftest']:selftest()
  elif sys.argv[1:]==['tick']:
   result=run();print(json.dumps(result,sort_keys=True))
   if result['status']!='GATUS_PUSH_CONFIRMED':sys.exit(2)
  else:raise RuntimeError('EXPECTED_SELFTEST_OR_TICK')
 except Exception as e:
  print(json.dumps({'status':'SAFE_STOP','error_class':type(e).__name__,'reason':str(e)[:90],
    'telegram_calls':0,'new_pollers':0,'publications_triggered':0},sort_keys=True))
  sys.exit(3)
