#!/usr/bin/env python3
"""NAS photo-news review list. Creates local HTML/JSON only; no Telegram calls.
All candidate texts/URLs are escaped; pending approval stays pending.
"""
import argparse,datetime,html,json,os,pathlib,sqlite3,sys,tempfile,time
STATE=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE")
DB=STATE/"migration_shadow.sqlite3"
HTML=STATE/"local_review_queue.html"
SUMMARY=STATE/"local_review_queue_status.json"
MAX_ROWS=200
HOURS=36
def read_rows(db_path,now=None):
 now=int(time.time()) if now is None else now
 db=sqlite3.connect("file:"+str(db_path)+"?mode=ro",uri=True,timeout=5)
 try:
  db.execute("PRAGMA busy_timeout=2000")
  table={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if not {"events","moderation_projection"}<=table:raise ValueError("projection_not_initialized")
  pairs=db.execute("SELECT candidate_id,headline,image_url,source_url,status,decision FROM moderation_projection ORDER BY rowid DESC LIMIT ?",(MAX_ROWS,)).fetchall()
  metadata={}
  for (payload,) in db.execute("SELECT payload FROM events WHERE kind='news_candidate' ORDER BY rowid DESC LIMIT 4000"):
   try:
    doc=json.loads(payload)
    cid=doc.get("candidate_id")
    if isinstance(cid,str) and cid not in metadata:metadata[cid]=doc.get("detected_at")
   except (ValueError,TypeError):pass
  result=[]
  for cid,headline,image,url,status,decision in pairs:
   epoch=metadata.get(cid)
   fresh=isinstance(epoch,int) and not isinstance(epoch,bool) and (now-HOURS*3600)<=epoch<=(now+300)
   result.append({"candidate_id":cid,"headline":headline or "","image_url":image or "","source_url":url or "","status":status,"decision":decision,"fresh":fresh,"published_at":epoch})
  return result
 finally:db.close()
def render(rows,now=None):
 now=int(time.time()) if now is None else now
 counts={"awaiting_review":0,"ready_shadow":0,"rejected":0,"deferred":0,"invalid":0,"stale":0}
 for row in rows:
  state=row["status"]
  counts[state]=counts.get(state,0)+1
  if not row["fresh"]:counts["stale"]+=1
 def esc(v):return html.escape(str(v),quote=True)
 cards=[]
 for row in rows:
  title=esc(row["headline"])
  url=esc(row["source_url"])
  image=esc(row["image_url"])
  cid=esc(row["candidate_id"])
  status=esc(row["status"])
  fresh="Свіжа" if row["fresh"] else "ПОТРЕБУЄ ПЕРЕВІРКИ ДАТИ"
  published=row["published_at"]
  when=datetime.datetime.fromtimestamp(published,datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if isinstance(published,int) and published>0 else "Час публікації невідомий"
  cards.append('<article><img loading="lazy" referrerpolicy="no-referrer" src="'+image+'" alt="Фото новини"><div class="content"><small>'+esc(fresh)+' • '+status+' • '+esc(when)+'</small><h3>'+title+'</h3><p>ID: <code>'+cid+'</code></p><a rel="noopener noreferrer" target="_blank" href="'+url+'">Відкрити першоджерело</a></div></article>')
 info='<h2>Новини NAS: '+str(len(rows))+' | Очікують модерації: '+str(counts.get("awaiting_review",0))+' | Потребують перевірки дати: '+str(counts["stale"])+'</h2>'
 header='''<!doctype html><html lang="uk"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src https:; base-uri 'none'; form-action 'none'">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RG Telegram — локальна черга перевірки</title>
<style>body{background:#11161e;color:#f7f7f7;font:15px system-ui,sans-serif;margin:26px auto;max-width:1140px;padding:0 14px}h1{font-size:26px}h2{font-size:18px}p,small{color:#b6bdc9}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}article{background:#202a36;border:1px solid #324052;border-radius:12px;overflow:hidden}img{object-fit:contain;background:#131a22;width:100%;height:200px}.content{padding:12px}a{color:#8fc9ff}code{color:#ffd9aa}</style></head><body>
<h1>RG Telegram — локальна модерація (тільки перегляд)</h1>
<p>Публікації вимкнені. Зображення завантажуються лише під час перегляду з браузера. Перевіряй водяні знаки, достовірність і якість матеріалів.</p>'''
 return header+info+"<main>"+"".join(cards)+"</main></body></html>",counts
def write_atomic(path,content):
 if path.is_symlink():raise ValueError("output_symlink")
 path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix=".rg-review-",dir=str(path.parent))
 try:
  with os.fdopen(fd,"w",encoding="utf-8") as f:f.write(content)
  os.chmod(tmp,0o640);os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def run(db_path,html_path,json_path):
 if not db_path.is_file() or db_path.is_symlink():raise ValueError("database_missing")
 rows=read_rows(db_path)
 page,counts=render(rows)
 write_atomic(html_path,page)
 state={"status":"LOCAL_REVIEW_EXPORTED","total":len(rows),"states":counts,"html_file":str(html_path),"delivery_enabled":False,"telegram_sends":0,"network_calls":0}
 write_atomic(json_path,json.dumps(state,ensure_ascii=False,indent=2)+"\n")
 return state
def selftest():
 with tempfile.TemporaryDirectory() as tmp:
  d=pathlib.Path(tmp)
  dbp=d/"test.db"
  with sqlite3.connect(str(dbp)) as conn:
   conn.execute("CREATE TABLE events(event_id TEXT PRIMARY KEY,kind TEXT,payload TEXT,created_at INTEGER,state TEXT)")
   conn.execute("CREATE TABLE moderation_projection(candidate_id TEXT,headline TEXT,image_url TEXT,source_url TEXT,status TEXT,decision TEXT)")
   conn.execute("INSERT INTO moderation_projection VALUES(?,?,?,?,?,?)",("aabbccddeeff","<script>alert(1)</script>","https://example.org/a.jpg","https://example.org/?q=1&x=2","awaiting_review","pending"))
   conn.execute("INSERT INTO events VALUES(?,?,?,?,?)",("n1","news_candidate",json.dumps({"candidate_id":"aabbccddeeff","detected_at":1000}),1000,"shadow"))
  htmlp=d/"review.html";state=run(dbp,htmlp,d/"status.json")
  assert state["total"]==1 and state["states"]["stale"]==1
  output=htmlp.read_text()
  assert "&lt;script&gt;" in output and "<script>" not in output
  assert "1&amp;x=2" in output and "тільки перегляд" in output
  assert not any(x in output for x in ("onclick=","<form","<button"))
 print(json.dumps({"selftest":"PASS","html_escaped":"PASS","stale_flag":"PASS","read_only_review":"PASS","telegram_sends":0}))
def main():
 parser=argparse.ArgumentParser()
 parser.add_argument("mode",choices=["selftest","once","status"])
 parser.add_argument("--db",default=str(DB))
 a=parser.parse_args()
 if a.mode=="selftest":selftest();return
 if a.mode=="status":
  if SUMMARY.is_file():print(SUMMARY.read_text())
  else:print(json.dumps({"status":"LOCAL_REVIEW_NOT_EXPORTED","telegram_sends":0}))
  return
 print(json.dumps(run(pathlib.Path(a.db),HTML,SUMMARY),ensure_ascii=False))
if __name__=="__main__":
 try:main()
 except Exception as exc:
  print(json.dumps({"status":"BLOCKED","reason":type(exc).__name__,"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
