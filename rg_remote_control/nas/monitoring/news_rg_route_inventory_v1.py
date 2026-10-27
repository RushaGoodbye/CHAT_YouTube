#!/usr/bin/env python3
"""Read-only NEWS RG routing inventory. Never executes production scripts."""
import os,sys,re,json,ast,pathlib,sqlite3,time
R=pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
names=['rg_v18.py','rg_news2_rss_hourly.py','rg_news2_outbound_queue_v2.py','rg_news2_private_final_guard_v1.py','operator/rg_news2_rss_hourly.py','operator/news_rg_editorial_rewrite_shadow_v1.py']
keywords=('rss','shadow','editorial','import','subprocess','run(','schedule','cron','source_cursor','story_shadow')
def info(path):
 if not path.is_file():return {'present':False}
 text=path.read_text(errors='replace')
 rows=text.splitlines();out={'present':True,'lines':len(rows),'bytes':len(text),'mtime_age_min':round((time.time()-path.stat().st_mtime)/60,1)}
 out['relevant_lines']=[{'n':i,'excerpt':line.strip()[:155]} for i,line in enumerate(rows,1) if any(w in line.lower() for w in keywords) and not any(w in line.lower() for w in ('token','password','secret','api_key','authorization','bearer')) and not re.search(r'(?i)(https?://|chat_id|bot[0-9]{7,})',line)][:55]
 try:
  tree=ast.parse(text);out['functions']=[x.name for x in tree.body if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef))][:35]
 except (SyntaxError,ValueError):pass
 return out
def main():
 if sys.argv[1:]==['selftest']:
  assert 'rss' in keywords;print('NEWS_RG_ROUTE_INVENTORY_SELFTEST_PASS');return
 if sys.argv[1:]!=['inspect']:raise SystemExit('selftest|inspect')
 result={'schema':'NEWS_RG_ROUTE_INVENTORY_V1','read_only':True,'telegram_calls':0,'db_writes':0,'publications':0,'modules':{n:info(R/n) for n in names}}
 db=R/'operator/news_rg_editorial_shadow_v1.sqlite3'
 if db.is_file():
  c=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
  c.execute('pragma query_only=ON')
  try:
   result['shadow']={'stories':c.execute('select count(*) from story_shadow').fetchone()[0], 'source_cursor_age_min':round((time.time()-c.execute('select max(last_scan_at) from source_cursor').fetchone()[0])/60,1)}
  finally:c.close()
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
