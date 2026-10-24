#!/usr/bin/env python3
"""RG Telegram News2 P27: investigate Cloudflare Telegram callback stealing risk
through deployed source snapshot, schedules and DB offsets. READ ONLY; no Telegram calls.
Does not dump source text, secrets, raw headers, or chat contents.
"""
import datetime,json,os,pathlib,re,sqlite3,sys
ROOT=pathlib.Path('/volume1/docker')
ALERTS=ROOT/'RG_ALERTS_DEPLOY'/'cloudflare-alerts'
NEWS=ROOT/'RG_TELEGRAM_NEWS_2'
TARGETS=[
 ('moderation','src/telegram-moderation.js'),
 ('manual_import','src/manual-import.js'),
 ('calendar','src/calendar-entry.js'),
 ('worker','src/index.js'),
 ('worker_alt','src/worker.js'),
 ('scheduled','src/scheduled.js'),
]
REGEXES={
 'getUpdates':r'getUpdates',
 'callback_query':r'callback_query',
 'rg3_button_prefix':r'rg3[:\\x27"\\x60]',
 'callback_data':r'callback_data',
 'answerCallbackQuery':r'answerCallbackQuery',
 'offset':r'\boffset\b',
 'moderation_processor':r'processTelegramModerationUpdates',
 'manual_processor':r'processManualTelegramImports',
 'scheduled_handler':r'\bscheduled\s*\(',
 'crons':r'\bcrons\b',
 'token_binding':r'TELEGRAM_BOT_TOKEN',
 'news2_literal':r'RG_TELEGRAM_NEWS_2|RushaGoodbyeNews_bot',
}
def read(p):
 try:
  if not p.is_file() or p.is_symlink() or p.stat().st_size>800000:
   return None
  return p.read_text('utf-8',errors='replace')
 except Exception:return None
def analyze(label,name):
 p=ALERTS/name
 s=read(p)
 if s is None:return {'name':name,'readable':False}
 lines=s.splitlines()
 hits={}
 for k,regex in REGEXES.items():
  rx=re.compile(regex,re.I)
  nums=[i for i,ln in enumerate(lines,1) if rx.search(ln)]
  if nums:hits[k]={'count':len(nums),'lines':nums[:12]}
 funcs=[]
 for i,ln in enumerate(lines,1):
  # Names and start lines only; NEVER source bodies or string literals.
  m=re.search(r'\b(?:async\s+)?function\s+([a-zA-Z_$][\w$]{0,75})\s*\(',ln)
  if m and any(w in m.group(1).lower() for w in ('telegram','moderation','poll','update','manual','schedule')):
   funcs.append({'name':m.group(1),'line':i})
 return {'name':name,'readable':True,'lines':len(lines),
  'relevant_markers':hits,'relevant_function_starts':funcs[:40]}
def line_window_markers(path,patterns):
 s=read(path)
 if s is None:return []
 lines=s.splitlines()
 rx=re.compile('|'.join(patterns),re.I)
 windows=[]
 for i,line in enumerate(lines):
  if 'getUpdates' not in line and not re.search(r'processTelegramModerationUpdates|processManualTelegramImports',line):continue
  begin=max(0,i-10);end=min(len(lines),i+12)
  segment='\n'.join(lines[begin:end])
  matches=[p for p in patterns if re.search(p,segment,re.I)]
  windows.append({'line':i+1,'nearby_markers':matches,
     'mentions_same_shared_secret_binding':bool(re.search('TELEGRAM_BOT_TOKEN',segment)),
     'mentions_offset':bool(re.search(r'\boffset\b',segment)),
     'mentions_callback_query':bool(re.search('callback_query',segment))})
 return windows[:35]
def cf_local_state():
 paths=['wrangler.toml','wrangler.json','wrangler.jsonc']
 found=[]
 for name in paths:
  s=read(ALERTS/name)
  if s is None:continue
  # Exclude literal URLs, account IDs, tokens; show triggers and binding names only.
  found.append({'config':name,
    'cron_schedule_present':bool(re.search(r'\bcrons\b',s)),
    'cron_expressions':re.findall(r'["\x27]((?:\*|\d+)(?:\s+(?:\*|\d+|\*/\d+|[0-9,-]+)){4})["\x27]',s)[:12],
    'telegram_bot_token_binding':bool(re.search(r'\bTELEGRAM_BOT_TOKEN\b',s)),
    'webhook_related':bool(re.search(r'webhook',s,re.I))})
 return found
def db_snapshot():
 dbfile=NEWS/'news.sqlite3'
 if not dbfile.is_file():return {'present':False}
 try:
  db=sqlite3.connect('file:'+str(dbfile)+'?mode=ro',uri=True,timeout=4)
  row=db.execute("SELECT value FROM moderation_meta WHERE key='offset'").fetchone()
  statuses=db.execute("SELECT status,count(*) FROM candidates GROUP BY status").fetchall()
  db.close()
  return {'present':True,'offset':int(row[0]) if row else None,'candidates':dict(statuses)}
 except Exception as e:return {'present':True,'error_type':type(e).__name__}
def p25_test():
 p=NEWS/'operator'
 found=[]
 for log in sorted(p.glob('p25_updates_*.json'))[-3:]:
  # Only counts, no secrets, callback text or message contents.
  try:
   d=json.loads(log.read_text('utf-8'))
   ups=d.get('updates',[])
   found.append({'file':log.name,'count':len(ups),
      'callbacks':sum(1 for u in ups if isinstance(u,dict) and 'callback_query' in u)})
  except Exception:pass
 return found
def main():
 if os.geteuid()!=0:
  print(json.dumps({'status':'P27_BLOCKED','reason':'SUDO_REQUIRED'}));sys.exit(1)
 result={'status':'NEWS2_P27_CLOUDFLARE_CALLBACK_ROUTING_STATIC_AUDIT',
  'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'source_files':[analyze(a,b) for a,b in TARGETS],
  'getUpdates_call_windows':{
   'telegram-moderation':line_window_markers(ALERTS/'src/telegram-moderation.js',
    ['callback_query','offset','TELEGRAM_BOT_TOKEN','rg3','await','processTelegramModerationUpdates']),
   'manual-import':line_window_markers(ALERTS/'src/manual-import.js',
    ['callback_query','offset','TELEGRAM_BOT_TOKEN','rg3','await','processManualTelegramImports'])},
  'cloudflare_local_config':cf_local_state(),
  'news2_db':db_snapshot(),
  'p25_archived_updates':p25_test(),
  'limits':'Cloudflare deployed secrets and active executions are not available in NAS source. This is code-path evidence, not proof of a competing deployed poller.',
  'telegram_api_calls':0,'secrets_exposed':False,'changes':0,'channel_sends':0}
 print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':main()
