#!/usr/bin/env python3
"""RG Telegram: NAS national minute of silence with approved existing PNG.
Schedule: 09:00..09:05 Europe/Kyiv only. Every send attempts once by daily key.
No bot polling, no Cloudflare API, no sending unless cutover gate verified.
"""
import argparse,datetime,json,os,pathlib,re,sqlite3,struct,sys,time,urllib.error,urllib.request,uuid
try:
 from zoneinfo import ZoneInfo
except ImportError:
 ZoneInfo=None  # Synology system Python 3.8 fallback
ROOT=pathlib.Path("/volume1/docker")
SECRETS=ROOT/"RG_SECRETS"
STATE=ROOT/"RG_TELEGRAM_STATE"
GATE=SECRETS/"rg_nas_telegram_cutover_enabled"
DB=STATE/"nas_native_schedule.sqlite3"
ASSETS=(
 ROOT/"RG_ALERTS_DEPLOY/cloudflare-alerts/public/minute-silence/approved.png",
 ROOT/"RG_CONTENT_DEPLOY/cloudflare-content-hub/public/templates/moment of silence.png"
)
TOKEN=SECRETS/"rg_telegram_bot_token"
CHANNEL="@RussiaGoodbyeUA"
class Fail(Exception):pass
def png_asset():
 for file in ASSETS:
  if file.is_symlink() or not file.is_file():continue
  if not 10000<=file.stat().st_size<=9_000_000:continue
  with file.open("rb") as f:head=f.read(24)
  if head[:8]!=b"\x89PNG\r\n\x1a\n" or head[12:16]!=b"IHDR":continue
  w,h=struct.unpack(">II",head[16:24])
  if 300<=w<=6000 and 300<=h<=6000:return file
 raise Fail("approved_png_not_available")
def permitted():
 if GATE.is_symlink() or not GATE.is_file() or GATE.stat().st_mode&0o077:
  raise Fail("nas_cutover_gate_closed")
 try:data=json.loads(GATE.read_text("utf-8"))
 except (OSError,ValueError):raise Fail("nas_cutover_gate_bad_json") from None
 if data.get("cloudflare_polling_disabled_verified") is not True or data.get("nas_single_poll_owner") is not True:
  raise Fail("nas_cutover_not_verified")
 # Selective moderation handoff leaves Cloudflare's minute-silence owner active.
 # Never allow both Cloudflare and NAS to send the same 09:00 memorial image.
 if data.get("selective_moderation_handoff") is True:
  raise Fail("minute_silence_stays_on_cloudflare")
 return True
def kyiv_now(now=None):
 """Correct Europe/Kyiv wall-clock on Python 3.8+ including EU DST switch.

 Prefer IANA tzdb on Python >=3.9; fallback uses the European rule
 effective in modern Ukraine: DST from 01:00 UTC last Sunday in March
 to 01:00 UTC last Sunday in October. No server-TZ assumptions.
 """
 d=now or datetime.datetime.now(datetime.timezone.utc)
 if d.tzinfo is None:raise Fail("clock_timezone_required")
 d=d.astimezone(datetime.timezone.utc)
 if ZoneInfo is not None:
  try:return d.astimezone(ZoneInfo("Europe/Kyiv"))
  except (KeyError,OSError):
   pass
 def last_sunday(year,month):
  last=datetime.date(year,month,31)
  return last.day-((last.weekday()+1)%7)
 y=d.year
 start=datetime.datetime(y,3,last_sunday(y,3),1,0,tzinfo=datetime.timezone.utc)
 stop=datetime.datetime(y,10,last_sunday(y,10),1,0,tzinfo=datetime.timezone.utc)
 delta=datetime.timedelta(hours=3 if start<=d<stop else 2)
 return (d+delta).replace(tzinfo=datetime.timezone(delta))
def due(now=None):
 d=kyiv_now(now)
 return d.strftime("%Y-%m-%d"),(d.hour==9 and 0<=d.minute<=5)
def init(db):
 db.execute("PRAGMA busy_timeout=5000")
 db.execute("""CREATE TABLE IF NOT EXISTS scheduled_publications(
  date_key TEXT NOT NULL,kind TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('attempt_started','published','delivery_uncertain')),
  attempted_at INTEGER NOT NULL,message_id INTEGER,
  PRIMARY KEY(date_key,kind))""")
def reserve(db,key,now):
 db.execute("BEGIN IMMEDIATE")
 try:
  changed=db.execute("INSERT OR IGNORE INTO scheduled_publications VALUES(?,'minute_silence','attempt_started',?,NULL)",(key,now)).rowcount
  db.execute("COMMIT")
  return changed==1
 except Exception:
  db.execute("ROLLBACK");raise
def send_image(path,token):
 boundary="rg_"+uuid.uuid4().hex
 payload=path.read_bytes()
 parts=[]
 def field(name,data,filename=None,typ=None):
  hdr=f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\""
  if filename:hdr+=f"; filename=\"{filename}\""
  hdr+="\r\n"
  if typ:hdr+=f"Content-Type: {typ}\r\n"
  hdr+="\r\n"
  parts.append(hdr.encode()+data+b"\r\n")
 field("chat_id",CHANNEL.encode())
 field("disable_notification",b"false")
 field("photo",payload,"minute-silence-approved.png","image/png")
 body=b"".join(parts)+f"--{boundary}--\r\n".encode()
 req=urllib.request.Request("https://api.telegram.org/bot"+token+"/sendPhoto",
  data=body,headers={"Content-Type":"multipart/form-data; boundary="+boundary,
  "User-Agent":"RG-NAS-Silence/1"},method="POST")
 try:
  with urllib.request.urlopen(req,timeout=16) as resp:
   raw=resp.read(32768)
 except (urllib.error.HTTPError,urllib.error.URLError,OSError,TimeoutError):
  raise Fail("delivery_uncertain") from None
 try:res=json.loads(raw)
 except ValueError:raise Fail("delivery_uncertain") from None
 msgid=(res.get("result") or {}).get("message_id") if res.get("ok") else None
 if not isinstance(msgid,int) or msgid<=0:raise Fail("delivery_uncertain")
 return msgid
def run(db,now=None,transport=send_image,asset_provider=png_asset):
 key,eligible=due(now)
 if not eligible:return {"status":"NOT_DUE","key":key,"window":"09:00-09:05 Europe/Kyiv","telegram_sends":0}
 permitted()
 asset=asset_provider()
 # Validate static inputs BEFORE creating the irreversible single-attempt row.
 if TOKEN.is_symlink() or not TOKEN.is_file() or TOKEN.stat().st_mode&0o077:
  raise Fail("token_unavailable")
 token=TOKEN.read_text("utf-8").strip()
 if not re.fullmatch(r"\d{5,13}:[A-Za-z0-9_-]{25,}",token):
  raise Fail("token_invalid")
 now_ts=int(time.time()) if now is None else int(now.timestamp())
 if not reserve(db,key,now_ts):
  prev=db.execute("SELECT state,message_id FROM scheduled_publications WHERE date_key=? AND kind='minute_silence'",(key,)).fetchone()
  return {"status":"DUPLICATE_BLOCKED","state":prev[0],"message_id":prev[1],"telegram_sends":0}
 try:
  message_id=transport(asset,token)
  db.execute("""UPDATE scheduled_publications SET state='published',message_id=?
    WHERE date_key=? AND kind='minute_silence' AND state='attempt_started'""",(message_id,key))
  return {"status":"MINUTE_SILENCE_PUBLISHED","date":key,"message_id":message_id,"telegram_send_attempts":1}
 except Fail:
  db.execute("UPDATE scheduled_publications SET state='delivery_uncertain' WHERE date_key=? AND kind='minute_silence' AND state='attempt_started'",(key,))
  return {"status":"DELIVERY_UNCERTAIN","date":key,"telegram_send_attempts":1,"auto_retry":False}
def selftest():
 from unittest.mock import patch
 example=datetime.datetime(2026,10,13,6,2,tzinfo=datetime.timezone.utc)
 assert due(example)==("2026-10-13",True)
 assert due(example+datetime.timedelta(minutes=4))[1] is False
 assert due(example-datetime.timedelta(minutes=3))[1] is False
 # Always exercise the Python 3.8 path even on newer build hosts.
 from unittest.mock import patch as mock_patch
 with mock_patch.dict(globals(),{"ZoneInfo":None}):
  assert due(example)==("2026-10-13",True)
  # European DST begins last Sunday in March and ends last Sunday in October.
  assert kyiv_now(datetime.datetime(2026,3,29,0,59,tzinfo=datetime.timezone.utc)).hour==2
  assert kyiv_now(datetime.datetime(2026,3,29,1,0,tzinfo=datetime.timezone.utc)).hour==4
  assert kyiv_now(datetime.datetime(2026,10,25,0,59,tzinfo=datetime.timezone.utc)).hour==3
  assert kyiv_now(datetime.datetime(2026,10,25,1,0,tzinfo=datetime.timezone.utc)).hour==3

 with sqlite3.connect(":memory:",isolation_level=None) as db:
  init(db)
  assert reserve(db,"2026-10-13",1)
  assert not reserve(db,"2026-10-13",2)
  assert db.execute("SELECT count(*) FROM scheduled_publications").fetchone()[0]==1
 # A moderation-only migration must never authorize duplicate minute silence.
 import tempfile
 with tempfile.TemporaryDirectory() as td:
  fake=pathlib.Path(td)/"cutover.json"
  fake.write_text(json.dumps({"cloudflare_polling_disabled_verified":True,
   "nas_single_poll_owner":True,"selective_moderation_handoff":True}))
  os.chmod(fake,0o600)
  with patch.dict(globals(),{"GATE":fake}):
   try:permitted()
   except Fail as ex:assert str(ex)=="minute_silence_stays_on_cloudflare"
   else:raise AssertionError("duplicate_minute_silence_possible")
 with patch.dict(globals(),{"GATE":pathlib.Path("/this/path/must/not/exist") }):
  try:permitted()
  except Fail:pass
  else:raise AssertionError("gate_bypassed")
 print(json.dumps({"selftest":"MINUTE_SILENCE_OFFLINE_PASS","kyiv_exact_window":"PASS",
  "durable_once_only":"PASS","cutover_gate":"PASS","telegram_sends":0,"network_calls":0}))
def main():
 p=argparse.ArgumentParser()
 p.add_argument("mode",choices=("selftest","status","once"))
 p.add_argument("--db",default=str(DB))
 args=p.parse_args()
 if args.mode=="selftest":selftest();return
 file=pathlib.Path(args.db)
 if file.is_symlink():raise Fail("db_symlink")
 if args.mode=="status":
  asset_ok=False
  try:png_asset();asset_ok=True
  except Fail:pass
  rows={}
  if file.is_file():
   with sqlite3.connect("file:"+str(file)+"?mode=ro",uri=True) as db:
    tables={x[0] for x in db.execute("SELECT name FROM sqlite_master")}
    if "scheduled_publications" in tables:
     rows=dict(db.execute("SELECT state,count(*) FROM scheduled_publications GROUP BY state"))
  print(json.dumps({"status":"MINUTE_SILENCE_NAS_PREPARED","canonical_asset_available":asset_ok,
   "cutover_gate_present":GATE.is_file(),"delivery_states":rows,"telegram_sends":0}))
  return
 file.parent.mkdir(parents=True,exist_ok=True)
 with sqlite3.connect(str(file),isolation_level=None,timeout=10) as db:
  init(db)
  result=run(db)
 print(json.dumps(result))
if __name__=="__main__":
 try:main()
 except Exception as e:
  allowed=e.args[0] if isinstance(e,Fail) else type(e).__name__
  print(json.dumps({"status":"BLOCKED","reason":allowed,"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
