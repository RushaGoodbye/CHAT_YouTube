#!/usr/bin/env python3
"""NEWS2 precise auth wiring audit. Read-only, redacted; no Telegram requests.
Identify source of bot token and moderator chat from actual running code.
"""
import ast,json,os,pathlib,re,sys
ROOT=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP=ROOT/'operator'
FILES=(OP/'news_rg_poll_moderation_v1.py',OP/'rg_poll_topnews_policy_v2.py',
 OP/'news_rg_durable_private_sender_v1.py',OP/'news_rg_continuous_callback_v1.py',
 ROOT/'rg_news_dsm_tick.sh')
KEYWORDS=re.compile(r'(?i)(telegram|bot.?token|tg.?token|secret|dotenv|chat.?id|moderator|authorization|load.?config|config|os\.environ|os\.getenv|read_text|open\(|decrypt|vault)')
STR=re.compile(r'(?P<quote>["\x27])(?:(?!(?P=quote)).|\\.)*(?P=quote)')
TOKEN=re.compile(r'\d{8,12}:[A-Za-z0-9_-]{30,60}')
def scrubs(line):
 line=TOKEN.sub('[REDACTED_TOKEN]',line)
 line=STR.sub('[STRING]',line)
 # Mask any assignment values, only on lines with suspicious key names
 if re.search(r'(?i)(TOKEN|SECRET|PASSWORD|API_KEY)\s*=',line):
  line=re.sub(r'(?<==).*',' [REDACTED]',line)
 return line.strip()[:180]
def inspect_python(p):
 src=p.read_text('utf8',errors='replace');lines=src.splitlines()
 tree=ast.parse(src)
 matches=[]
 for index,line in enumerate(lines,1):
  if KEYWORDS.search(line):
   matches.append({'line':index,'shape':scrubs(line)})
 # Limit to auth wiring at top of file + auth funcs, rather than huge unrelated methods
 selected=matches[:80]
 funcs=[]
 for n in ast.walk(tree):
  if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and re.search(r'(?i)(telegram|token|config|secret|moderator|chat|bot)',n.name):
   funcs.append({'name':n.name,'line':n.lineno,'args':[a.arg for a in n.args.args]})
 imports=[]
 for n in tree.body:
  if isinstance(n,ast.Import):imports.extend(alias.name for alias in n.names)
  if isinstance(n,ast.ImportFrom):imports.append(n.module or '(relative)')
 return {'path':str(p),'matched_lines':selected,'auth_related_functions':funcs[:35],
  'imports':imports[:35],'total_matches':len(matches)}
def inspect_shell(p):
 lines=p.read_text('utf8',errors='replace').splitlines()
 picks=[]
 for i,s in enumerate(lines,1):
  if KEYWORDS.search(s) or ('source ' in s or '. /' in s):
   picks.append({'line':i,'shape':scrubs(s)})
 return {'path':str(p),'relevant_lines':picks[:60]}
def json_keys(p):
 if not p.is_file():return None
 d=json.loads(p.read_text('utf8'))
 if not isinstance(d,dict):return {'path':str(p),'root_type':type(d).__name__}
 return {'path':str(p),'key_names':sorted(d.keys()),'moderation_chat_configured':bool(d.get('moderation_chat_id')),
  'moderators_count':len(d.get('moderators',[])) if isinstance(d.get('moderators'),list) else None}
def main():
 result={'status':'NEWS2_PRECISE_AUTH_WIRING_READONLY','scripts':[],'moderation_configs':[],
  'environment_key_names':[k for k in os.environ if re.search(r'(?i)(TELEGRAM|BOT|TOKEN|SECRET)',k)],
  'secrets_exposed':False,'telegram_calls':0,'publications':0,'new_pollers':0}
 for p in FILES:
  if not p.is_file() or p.is_symlink():continue
  result['scripts'].append(inspect_shell(p) if p.suffix=='.sh' else inspect_python(p))
 for p in (ROOT/'moderation.json',ROOT/'moderation.new_bot_pending.json'):
  try:
   j=json_keys(p)
   if j:result['moderation_configs'].append(j)
  except Exception as e:result['moderation_configs'].append({'path':str(p),'error':type(e).__name__})
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as e:
  print(json.dumps({'status':'NEWS2_AUTH_WIRING_SAFE_STOP','error':type(e).__name__,
   'telegram_calls':0,'publications':0},ensure_ascii=False));sys.exit(2)
