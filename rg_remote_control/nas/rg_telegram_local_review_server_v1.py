#!/usr/bin/env python3
"""RG Telegram: private local NAS review UI (shadow-only).
Listen on 127.0.0.1. Password protected. Never talks to Telegram/Cloudflare.
Requires SSH port forward for use from Windows.
"""
import argparse,base64,datetime,fcntl,hashlib,hmac,html,http.server,importlib.util,json,os,pathlib,secrets,socket,sqlite3,subprocess,sys,tempfile,time,urllib.parse,urllib.request
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
DB=STATE/"migration_shadow.sqlite3"
KEY=ROOT/"RG_SECRETS/rg_local_review_ui_password"
PORT=8767
APP="RG_NAS_LOCAL_REVIEW_V1"
UI_VERSION="2"
VALID_VIEWS=("pending","stale","ready_shadow","rejected","deferred","all")
LABELS={"pending":"Нові","stale":"Потрібна перевірка","ready_shadow":"Схвалені","rejected":"Відхилені","deferred":"Відкладені","all":"Усі"}
STATES={"awaiting_review":"Очікує модерації","ready_shadow":"Схвалено локально","rejected":"Відхилено","deferred":"Відкладено","invalid":"Помилка"}
def esc(v):return html.escape(str(v if v is not None else ""),quote=True)
def import_local(name):
 p=pathlib.Path(__file__).with_name(name)
 if not p.is_file():raise RuntimeError("missing_module:"+name)
 spec=importlib.util.spec_from_file_location(name[:-3],str(p))
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 return m
def csrf(key,cid,decision):
 return hmac.new(key.encode(),(cid+":"+decision).encode(),hashlib.sha256).hexdigest()
def password():
 if KEY.is_symlink():raise RuntimeError("password_symlink")
 if not KEY.is_file():
  KEY.parent.mkdir(parents=True,exist_ok=True)
  fd,tmp=tempfile.mkstemp(prefix=".rg-review-key-",dir=str(KEY.parent))
  try:
   os.fchmod(fd,0o600)
   with os.fdopen(fd,"w") as out:out.write(secrets.token_urlsafe(32)+"\n")
   os.replace(tmp,KEY)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
 if KEY.stat().st_mode & 0o077:os.chmod(KEY,0o600)
 text=KEY.read_text("utf-8").strip()
 if len(text)<32:raise RuntimeError("weak_password")
 return text
def safe_https_url(url):
 if not isinstance(url,str) or len(url)>1800:return ""
 try:
  p=urllib.parse.urlsplit(url)
  if p.scheme=="https" and p.hostname and not p.username and not p.password and not p.fragment and p.port in (None,443):
   return url
 except ValueError:pass
 return ""
def review_rows(db_path,now=None):
 now=int(time.time()) if now is None else int(now)
 with sqlite3.connect("file:"+str(db_path)+"?mode=ro",uri=True,timeout=4) as db:
  # No SQLite JSON1 extension required (Synology Python compatibility).
  dates={}
  for (raw,) in db.execute("SELECT payload FROM events WHERE kind='news_candidate' ORDER BY rowid DESC LIMIT 5000"):
   try:
    p=json.loads(raw);cid=p.get("candidate_id");ts=p.get("detected_at")
    if isinstance(cid,str) and cid not in dates and isinstance(ts,int) and not isinstance(ts,bool) and ts>0:
     dates[cid]=ts
   except (ValueError,TypeError):pass
  results=[]
  for cid,title,img,src,state,decision in db.execute(
    "SELECT candidate_id,headline,image_url,source_url,status,decision FROM moderation_projection ORDER BY rowid DESC LIMIT 150"):
   published=dates.get(cid,0)
   fresh=published>0 and now-36*3600<=published<=now+300
   results.append({"id":cid,"title":title or "","image":img or "","url":src or "","state":state,"decision":decision,"published":published,"fresh":fresh})
  return results
def filtered_rows(rows,view):
 if view=="pending":return [r for r in rows if r["state"]=="awaiting_review" and r["fresh"]]
 if view=="stale":return [r for r in rows if r["state"]=="awaiting_review" and not r["fresh"]]
 if view=="all":return list(rows)
 return [r for r in rows if r["state"]==view]
def render(rows,key,message="",view="pending",page_no=1):
 if view not in VALID_VIEWS:view="pending"
 counts={v:len(filtered_rows(rows,v)) for v in VALID_VIEWS}
 chosen=filtered_rows(rows,view)
 per_page=18
 pages=max(1,(len(chosen)+per_page-1)//per_page)
 page_no=max(1,min(page_no,pages))
 visible=chosen[(page_no-1)*per_page:page_no*per_page]
 css="""*{box-sizing:border-box}body{background:#0f141b;color:#f1f5f9;font:15px system-ui,sans-serif;margin:0}header{padding:20px 24px 10px;max-width:1240px;margin:auto}header h1{font-size:23px;margin:0 0 6px}header p{color:#a8b9cd;margin:8px 0}main{max-width:1240px;margin:0 auto;padding:10px 24px 30px;display:grid;grid-template-columns:repeat(auto-fill,minmax(400px,1fr));gap:16px}.card{border:1px solid #334154;border-radius:14px;background:#1b2633;overflow:hidden}.card img{display:block;object-fit:contain;width:100%;height:260px;background:#0e1620}.in{padding:15px}.headline{font-size:18px;line-height:1.38;margin:10px 0}.meta{color:#a8b8ca;font-size:12px}.state{font-size:12px;font-weight:700;padding:5px 9px;border-radius:8px;background:#344357;display:inline-block}.fresh{color:#a7e8c4}.old{color:#ffbb92}.actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.actions button{border:0;color:white;background:#28598d;border-radius:8px;padding:9px 12px;cursor:pointer;font:inherit}.actions button.reject{background:#913e4a}.actions button.defer{background:#74592f}input[type=checkbox]{width:18px;height:18px;vertical-align:middle}label{font-size:13px;color:#cbd6e5}a{color:#8bc6ff}.notice{padding:12px 14px;background:#273b53;border-radius:10px}.nav{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}.nav a{display:inline-flex;gap:7px;padding:10px 12px;text-decoration:none;border:1px solid #344357;border-radius:9px;color:#cad7e9;background:#192635}.nav a.sel{background:#315880;border-color:#73a8d5;color:white}.nav strong{font-variant-numeric:tabular-nums}.warning{border-left:3px solid #e5a657;padding:10px 13px;background:#2f2a26;color:#f4dfc2;border-radius:5px;margin-top:14px}.pages{margin:0 auto 30px;max-width:1240px;padding:0 24px;display:flex;gap:10px;align-items:center}.pages a{padding:9px 12px;border:1px solid #3b5b7c;border-radius:8px;text-decoration:none}.muted{font-size:13px;color:#99a9bf}.details{margin:12px 0}.details summary{cursor:pointer;color:#9abbd6}.empty{padding:35px 10px;color:#c1d3e7;text-align:center;grid-column:1/-1}@media(max-width:600px){header{padding:18px 12px 8px}main{padding:8px 12px;grid-template-columns:1fr}.card img{height:220px}.nav a{padding:8px 10px}.actions button{flex:1}}"""
 chunks=['<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
 '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src https:; form-action \'self\'; base-uri \'none\'; frame-ancestors \'none\'">',
 '<meta name="referrer" content="no-referrer"><title>RG Telegram | NAS модерація</title><style>',css,'</style></head><body><header>',
 '<h1>RG Telegram | NAS модерація</h1><p>Локальна черга SQLite · Cloudflare не використовується · Публікацію в Telegram вимкнено</p>']
 if message:chunks+=['<p class="notice">',esc(message),'</p>']
 chunks+=['<nav class="nav" aria-label="Фільтри новин">']
 for name in VALID_VIEWS:
  chunks+=['<a class="',('sel' if view==name else ''),'" href="/?view=',name,'">',esc(LABELS[name]),' <strong>',str(counts[name]),'</strong></a>']
 chunks+=['</nav><p class="warning">Перед схваленням перевірте достовірність новини, фотографію, водяні знаки, чужі логотипи та можливі обрізані написи. Виявили порушення — відхиліть матеріал до заміни фото.</p>',
 '<p class="muted">Показано ',str(len(visible)),' із ',str(len(chosen)),' матеріалів · сторінка ',str(page_no),' із ',str(pages),'</p></header><main>']
 if not visible:chunks+=['<div class="empty">У цьому розділі зараз немає матеріалів.</div>']
 for row in visible:
  cid=row["id"];safe_id=esc(cid);fresh=row["fresh"]
  published=row.get("published") or 0
  try:
   when=datetime.datetime.fromtimestamp(published,datetime.timezone.utc).strftime("%d.%m.%Y %H:%M UTC") if isinstance(published,int) and published>0 else "Дата відсутня"
  except (OSError,OverflowError,ValueError):when="Дата недійсна"
  chunks+=['<article class="card"><img loading="lazy" referrerpolicy="no-referrer" src="',esc(safe_https_url(row["image"])),'" alt="Фото новини">',
  '<div class="in"><span class="state">',esc(STATES.get(row["state"],row["state"])),'</span> <span class="meta '+('fresh' if fresh else 'old')+'">',
  ('Свіжа' if fresh else 'Дата не підтверджена / застаріла'),'</span><h3 class="headline">',esc(row["title"]),'</h3>',
  '<p class="meta">',esc(when),'</p><p><a target="_blank" rel="noopener noreferrer" href="',esc(safe_https_url(row["url"])),'">Перевірити першоджерело ↗</a></p>',
  '<details class="details"><summary>Технічні дані</summary><p class="meta">ID: ',safe_id,'</p></details>']
  if row["state"] in ("awaiting_review","deferred","ready_shadow"):
   chunks+=['<form method="post" action="/decision"><input type="hidden" name="candidate_id" value="',safe_id,'">',
   '<input type="hidden" name="return_view" value="',view,'">',
   '<label><input type="checkbox" name="verified" value="yes" required> Перевірено зміст, фото, логотипи, водяні знаки та обриви тексту</label><div class="actions">']
   for choice,label,klass in [("approved","Схвалити",""),("rejected","Відхилити","reject"),("deferred","Відкласти","defer")]:
    if choice=="approved" and (not fresh or row["state"]=="ready_shadow"):continue
    if choice=="deferred" and row["state"]=="deferred":continue
    if choice=="rejected" and row["state"]=="ready_shadow":label="Скасувати схвалення"
    chunks+=['<button type="submit" name="choice" value="',choice,'" class="',klass,'">',label,'</button>']
   chunks+=['<input type="hidden" name="csrf" value="',csrf(key,cid,"review"),'"></div></form>']
  chunks+=['</div></article>']
 chunks+=['</main><div class="pages">']
 if page_no>1:chunks+=['<a href="/?view=',view,'&page=',str(page_no-1),'">← Попередня</a>']
 chunks+=['<span class="muted">Сторінка ',str(page_no),' / ',str(pages),'</span>']
 if page_no<pages:chunks+=['<a href="/?view=',view,'&page=',str(page_no+1),'">Наступна →</a>']
 chunks+=['</div></body></html>']
 return ''.join(chunks)
class Handler(http.server.BaseHTTPRequestHandler):
 server_version="RG-NAS-Review/1.0"
 def log_message(self,fmt,*args):pass
 def common(self,status,kind,length):
  self.send_response(status)
  self.send_header("Content-Type",kind)
  self.send_header("Content-Length",str(length))
  self.send_header("Cache-Control","no-store")
  self.send_header("X-Content-Type-Options","nosniff")
  self.send_header("X-Frame-Options","DENY")
  self.send_header("Referrer-Policy","no-referrer")
  self.end_headers()
 def auth(self):
  header=self.headers.get("Authorization","")
  try:
   scheme,data=header.split(" ",1)
   raw=base64.b64decode(data,validate=True).decode()
   user,passwd=raw.split(":",1)
   if scheme.lower()=="basic" and user=="rg" and hmac.compare_digest(passwd,self.server.access_key):return True
  except (ValueError,UnicodeError):pass
  body=b"Authentication required"
  self.send_response(401);self.send_header("WWW-Authenticate",'Basic realm="RG Telegram NAS Review"')
  self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
  return False
 def do_GET(self):
  if self.path=="/health":
   data=json.dumps({"app":APP,"status":"READY","shadow_only":True,"telegram_sends":0,"ui_version":UI_VERSION}).encode()
   self.common(200,"application/json",len(data));self.wfile.write(data);return
  url=urllib.parse.urlsplit(self.path)
  if url.path!="/":
   self.send_error(404);return
  if not self.auth():return
  try:
   query=urllib.parse.parse_qs(url.query)
   view=(query.get("view") or ["pending"])[0]
   if view not in VALID_VIEWS:view="pending"
   raw_page=(query.get("page") or ["1"])[0]
   page_no=int(raw_page) if raw_page.isdigit() and len(raw_page)<=4 else 1
   notice={"approved":"Новину схвалено локально. У Telegram не відправлено.","rejected":"Новину відхилено.","deferred":"Новину відкладено."}.get((query.get("done") or [""])[0],"")
   rows=review_rows(self.server.db_path)
   page=render(rows,self.server.access_key,notice,view,page_no).encode("utf-8")
  except (sqlite3.Error,ValueError,RuntimeError):
   self.send_error(503);return
  self.common(200,"text/html; charset=utf-8",len(page));self.wfile.write(page)
 def do_POST(self):
  if self.path!="/decision":self.send_error(404);return
  if not self.auth():return
  try:
   n=int(self.headers.get("Content-Length","0"))
   if not 0<n<=1600:raise ValueError("invalid_length")
   payload=urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8"),strict_parsing=True)
   def only(k):
    v=payload.get(k,[])
    if len(v)!=1:raise ValueError("invalid_field:"+k)
    return v[0]
   cid=only("candidate_id")
   choice=only("choice")
   return_view=only("return_view")
   if return_view not in VALID_VIEWS:raise ValueError("invalid_return_view")
   assert_flag=only("verified")
   token=only("csrf")
   if not hmac.compare_digest(token,csrf(self.server.access_key,cid,"review")):raise ValueError("csrf_mismatch")
   if assert_flag!="yes":raise ValueError("operator_verification_required")
   local=import_local("rg_telegram_local_review_decision_v1.py")
   local.submit(self.server.db_path,cid,choice,confirmed=True)
   projection=import_local("rg_telegram_moderation_projection_v1.py")
   with sqlite3.connect(str(self.server.db_path),timeout=10,isolation_level=None) as db:
    projection.setup(db);projection.process(db)
  except (ValueError,sqlite3.Error,RuntimeError,UnicodeError):
   self.send_error(400,"Request denied");return
  self.send_response(303);self.send_header("Location","/?view="+return_view+"&done="+choice)
  self.send_header("Cache-Control","no-store");self.send_header("Content-Length","0");self.end_headers()
def health():
 try:
  with urllib.request.urlopen("http://127.0.0.1:"+str(PORT)+"/health",timeout=1.5) as resp:doc=json.loads(resp.read(3000))
  return doc.get("app")==APP and doc.get("status")=="READY"
 except Exception:return False
def serve():
 server=http.server.ThreadingHTTPServer(("127.0.0.1",PORT),Handler)
 server.access_key=password()
 server.db_path=DB
 print(json.dumps({"status":"LISTENING_LOOPBACK","port":PORT,"shadow_only":True}),flush=True)
 server.serve_forever(poll_interval=0.5)
def ensure():
 lock=STATE/".local_review_ui_ensure.lock"
 lock.parent.mkdir(parents=True,exist_ok=True)
 with lock.open("w") as control:
  fcntl.flock(control,fcntl.LOCK_EX)
  if health():
   print(json.dumps({"status":"LOCAL_REVIEW_UI_READY","port":PORT,"telegram_sends":0}));return
  # Keep the password outside logs; generate one only if not present.
  password()
  log=STATE/"local_review_ui.log"
  with log.open("ab") as output:
   subprocess.Popen([sys.executable,str(pathlib.Path(__file__).resolve()),"serve"],stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,close_fds=True,start_new_session=True)
  for n in range(15):
   time.sleep(0.2)
   if health():
    print(json.dumps({"status":"LOCAL_REVIEW_UI_STARTED","port":PORT,"telegram_sends":0}));return
  raise RuntimeError("service_start_failed_or_port_busy")
def selftest():
 key="test-secret-not-for-production"
 row={"id":"aabbccddeeff","title":"<script>alert(1)</script>","image":"https://example.org/photo.jpg","url":"https://example.org/?a=1&b=2","state":"awaiting_review","decision":"pending","published":100,"fresh":False}
 fresh={**row,"id":"123456abcdef","state":"awaiting_review","title":"Новина з якісним фото","fresh":True}
 assert filtered_rows([row,fresh],"pending")==[fresh]
 assert filtered_rows([row,fresh],"stale")==[row]
 page=render([row,fresh],key,view="stale")
 assert "<script>" not in page and "&lt;script&gt;" in page
 assert "a=1&amp;b=2" in page
 assert "Схвалити" not in page
 assert "Відхилити" in page and "Відкласти" in page
 assert "awaiting_review</span>" not in page
 assert "Водяні знаки" not in page
 assert "водяні знаки" in page
 page2=render([row,fresh],key,view="pending")
 assert "Схвалити" in page2 and "Нові" in page2 and 'value="pending"' in page2
 assert 'href="/?view=stale"' in page2
 assert safe_https_url("javascript:alert(1)")==""
 assert safe_https_url("https://example.org/")=="https://example.org/"
 assert csrf(key,row["id"],"review") in page
 assert csrf(key,row["id"],"review")!=csrf(key,"otherid","review")
 assert 'Схвалити' not in render([row],key,view="stale")
 assert len(filtered_rows([row]*50,"stale"))==50
 assert 'Наступна →' in render([fresh]*19,key,view="pending")
 assert '← Попередня' in render([fresh]*19,key,view="pending",page_no=2)
 print(json.dumps({"selftest":"PASS","ui_version":UI_VERSION,"escaped_markup":"PASS","tabs":"PASS","pagination":"PASS","stale_approval_blocked":"PASS","watermark_review":"MANUAL","csrf":"PASS","loopback_only":True,"telegram_sends":0}))
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("mode",choices=["selftest","serve","ensure","status"]);a=p.parse_args()
 if a.mode=="selftest":selftest()
 elif a.mode=="serve":serve()
 elif a.mode=="ensure":ensure()
 else:print(json.dumps({"status":"LOCAL_REVIEW_UI_READY" if health() else "LOCAL_REVIEW_UI_NOT_RUNNING","port":PORT,"telegram_sends":0}))
