#!/usr/bin/env python3
"""RG Telegram: private local NAS review UI (shadow-only).
Listen on 127.0.0.1. Password protected. Never talks to Telegram/Cloudflare.
Requires SSH port forward for use from Windows.
"""
import argparse,base64,fcntl,hashlib,hmac,html,http.server,importlib.util,json,os,pathlib,secrets,socket,sqlite3,subprocess,sys,tempfile,time,urllib.parse,urllib.request
ROOT=pathlib.Path("/volume1/docker")
STATE=ROOT/"RG_TELEGRAM_STATE"
DB=STATE/"migration_shadow.sqlite3"
KEY=ROOT/"RG_SECRETS/rg_local_review_ui_password"
PORT=8767
APP="RG_NAS_LOCAL_REVIEW_V1"
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
def render(rows,key,message=""):
 counts={}
 for row in rows:counts[row["state"]]=counts.get(row["state"],0)+1
 count=counts.get("awaiting_review",0)
 css="""body{background:#10151c;color:#f1f5f9;font:15px system-ui;margin:0}header{padding:20px;max-width:1200px;margin:auto}header h1{font-size:24px;margin:0}header p{color:#9faec1}main{max-width:1200px;margin:0 auto;padding:8px 20px 35px;display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}.card{border:1px solid #354052;border-radius:14px;background:#1b2633;overflow:hidden}.card img{display:block;object-fit:contain;width:100%;height:190px;background:#111a24}.in{padding:14px}.headline{font-size:17px;line-height:1.35}.meta{color:#a8b6c8;font-size:12px}.badge{font-size:12px;font-weight:700;padding:5px 8px;border-radius:8px;background:#374357;display:inline-block}.fresh{color:#a2e8c2}.old{color:#ffbc95}.actions{display:flex;gap:5px;flex-wrap:wrap;margin-top:12px}.actions button{border:0;color:#fff;background:#2b5589;border-radius:8px;padding:9px 12px;cursor:pointer;font:inherit}.actions button.reject{background:#933e4b}.actions button.defer{background:#74582e}input[type=checkbox]{width:17px;height:17px}label{font-size:13px;color:#cbd6e5}a{color:#87baff}.notice{padding:10px;background:#31445c;border-radius:9px}"""
 htmls=['<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
 '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src https:; form-action \'self\'; base-uri \'none\'; frame-ancestors \'none\'">',
 '<meta name="referrer" content="no-referrer"><title>RG Telegram | NAS модерація</title><style>',css,'</style></head><body><header>',
 '<h1>RG Telegram | NAS модерація</h1><p>Без Cloudflare. Записи в локальній SQLite. Публікація у Telegram ВИМКНЕНА.</p>',
 '<p>Очікують модерації: <strong>',str(count),'</strong> | Усього показано: ',str(len(rows)),'</p>']
 if message:htmls+=['<p class="notice">',esc(message),'</p>']
 htmls+=['</header><main>']
 for row in rows:
  cid=row["id"]
  safe_id=esc(cid)
  fresh=row["fresh"]
  htmls+=['<article class="card"><img loading="lazy" referrerpolicy="no-referrer" src="',esc(row["image"]),'" alt="Фото новини"><div class="in"><span class="badge">',esc(row["state"]),'</span> ',
    '<span class="meta '+('fresh' if fresh else 'old')+'">',('Свіжа новина' if fresh else 'Дата не підтверджена / застаріла'),'</span>',
    '<h3 class="headline">',esc(row["title"]),'</h3><p class="meta">',safe_id,'</p><p><a target="_blank" rel="noopener noreferrer" href="',esc(row["url"]),'">Перевірити першоджерело</a></p>']
  if row["state"] not in ("rejected",):
   htmls+=['<form method="post" action="/decision"><input type="hidden" name="candidate_id" value="',safe_id,'">']
   htmls+=['<label><input type="checkbox" name="verified" value="yes" required> Я перевірив(ла) зміст, фото та відсутність чужих водяних знаків</label><div class="actions">']
   for choice,label,klass in [("approved","Схвалити",""),("rejected","Відхилити","reject"),("deferred","Відкласти","defer")]:
    if choice=="approved" and not fresh:continue
    # Token is scoped to individual action and candidate, not a global CSRF bypass.
    htmls+=['<button type="submit" name="choice" value="',choice,'" class="',klass,'">',label,'</button>']
   # Use a single CSRF per candidate, independently of the pressed button.
   htmls+=['<input type="hidden" name="csrf" value="',csrf(key,cid,"review"),'"></div></form>']
  htmls+=['</div></article>']
 htmls+=['</main></body></html>']
 return ''.join(htmls)
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
   data=json.dumps({"app":APP,"status":"READY","shadow_only":True,"telegram_sends":0}).encode()
   self.common(200,"application/json",len(data));self.wfile.write(data);return
  if self.path!="/":
   self.send_error(404);return
  if not self.auth():return
  try:
   rows=review_rows(self.server.db_path)
   page=render(rows,self.server.access_key).encode("utf-8")
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
  self.send_response(303);self.send_header("Location","/")
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
 page=render([row],key)
 assert "<script>" not in page
 assert "&lt;script&gt;" in page
 assert "a=1&amp;b=2" in page
 assert "Схвалити" not in page
 assert "Відхилити" in page and "Відкласти" in page
 assert safe_https_url("javascript:alert(1)") == ""
 assert safe_https_url("https://example.org/")=="https://example.org/"
 assert csrf(key,row["id"],"review") in page
 assert csrf(key,row["id"],"review")!=csrf(key,"otherid","review")
 assert hmac.compare_digest(csrf(key,row["id"],"review"),csrf(key,row["id"],"review"))
 print(json.dumps({"selftest":"PASS","escaped_markup":"PASS","stale_approval_blocked":"PASS","csrf":"PASS","loopback_only":True,"telegram_sends":0}))
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("mode",choices=["selftest","serve","ensure","status"]);a=p.parse_args()
 if a.mode=="selftest":selftest()
 elif a.mode=="serve":serve()
 elif a.mode=="ensure":ensure()
 else:print(json.dumps({"status":"LOCAL_REVIEW_UI_READY" if health() else "LOCAL_REVIEW_UI_NOT_RUNNING","port":PORT,"telegram_sends":0}))
