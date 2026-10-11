#!/usr/bin/env python3
"""RG Telegram NAS: ingest local scanner candidates to shadow SQLite.
File-only spool. No network, Telegram, Cloudflare or publishing.
Input: one JSON object per line with source_url, image_url, headline,
optional candidate_id (12 lowercase hex), detected_at (Unix seconds).
"""
import argparse,hashlib,importlib.util,json,pathlib,re,sqlite3,sys,tempfile,time,urllib.parse
STATE=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE")
DEFAULT_DB=STATE/"migration_shadow.sqlite3"
DEFAULT_INBOX=STATE/"candidate_inbox.jsonl"
MAX_BYTES=2097152
MAX_LINES=5000
def https_url(url):
 if not isinstance(url,str) or len(url)>1800:return False
 try:
  p=urllib.parse.urlsplit(url)
  return p.scheme=="https" and bool(p.hostname) and not p.username and not p.password and not p.fragment and p.port in (None,443)
 except ValueError:return False
def candidate(row):
 if not isinstance(row,dict):raise ValueError("candidate_not_object")
 headline=row.get("headline")
 source=row.get("source_url")
 image=row.get("image_url")
 if not isinstance(headline,str) or not 18<=len(headline.strip())<=400:raise ValueError("headline_invalid")
 if not https_url(source):raise ValueError("source_url_invalid")
 if not https_url(image):raise ValueError("image_url_invalid")
 cid=row.get("candidate_id") or hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
 if not isinstance(cid,str) or not re.fullmatch("[0-9a-f]{12}",cid):raise ValueError("candidate_id_invalid")
 detected=row.get("detected_at")
 if detected is None:detected=0
 if isinstance(detected,bool) or not isinstance(detected,int) or detected<0:raise ValueError("detected_at_invalid")
 return {"event_id":"nasnews:"+cid,"kind":"news_candidate","source":"nas-local-spool","payload":{"candidate_id":cid,"headline":headline.strip(),"source_url":source,"image_url":image,"detected_at":detected}}
def intake_module():
 f=pathlib.Path(__file__).with_name("rg_telegram_nas_event_intake_v1.py")
 if not f.is_file():raise ValueError("event_intake_missing")
 spec=importlib.util.spec_from_file_location("nas_intake",str(f))
 m=importlib.util.module_from_spec(spec)
 spec.loader.exec_module(m)
 return m
def once(db_path,inbox_path):
 if db_path.is_symlink() or not db_path.is_file():raise ValueError("db_missing")
 if inbox_path.is_symlink():raise ValueError("inbox_symlink")
 if not inbox_path.is_file():
  return {"status":"NO_LOCAL_CANDIDATES","lines":0,"stored":0,"duplicates":0,"invalid":0,"conflicts":0,"telegram_sends":0}
 if inbox_path.stat().st_size>MAX_BYTES:raise ValueError("inbox_too_large")
 mod=intake_module()
 stats={"status":"LOCAL_INGEST_OK","lines":0,"stored":0,"duplicates":0,"invalid":0,"conflicts":0,"telegram_sends":0}
 with sqlite3.connect(str(db_path),timeout=10,isolation_level=None) as db:
  mod.init(db)
  with inbox_path.open("r",encoding="utf-8") as handle:
   for n,line in enumerate(handle,1):
    if n>MAX_LINES:raise ValueError("inbox_too_many_lines")
    if not line.strip():continue
    stats["lines"]+=1
    try:
     ev=candidate(json.loads(line))
     result=mod.intake(db,ev)
     if result=="SHADOW_STORED":stats["stored"]+=1
     elif result=="DUPLICATE":stats["duplicates"]+=1
    except (ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
     if "event_id_conflict" in str(exc):stats["conflicts"]+=1
     else:stats["invalid"]+=1
 return stats
def selftest():
 mod=intake_module()
 with tempfile.TemporaryDirectory() as tmp:
  base=pathlib.Path(tmp)
  dbp=base/"db.sqlite"
  inbox=base/"spool.jsonl"
  with sqlite3.connect(str(dbp),isolation_level=None) as db:
   db.execute("CREATE TABLE events(event_id TEXT PRIMARY KEY,kind TEXT,payload TEXT,created_at INTEGER,state TEXT)")
  example={"candidate_id":"aabbccddeeff","headline":"Підтверджена новина з фотографією","source_url":"https://example.org/news/1","image_url":"https://example.org/image/1.jpg"}
  inbox.write_text(json.dumps(example,ensure_ascii=False)+"\n"+json.dumps(example,ensure_ascii=False)+"\n"+json.dumps({**example,"image_url":""},ensure_ascii=False)+"\n","utf-8")
  a=once(dbp,inbox)
  assert a["stored"]==1 and a["duplicates"]==1 and a["invalid"]==1,a
  b=once(dbp,inbox)
  assert b["stored"]==0 and b["duplicates"]==2,b
  with sqlite3.connect(str(dbp)) as db:
   assert db.execute("SELECT count(*) FROM events WHERE kind='news_candidate'").fetchone()[0]==1
  assert not https_url("http://example.org/asset.jpg")
  assert not https_url("https://user:pass@example.org/a")
  assert not https_url("https://example.org/a#fragment")
 print(json.dumps({"selftest":"PASS","inbox_dedup":"PASS","required_image":"PASS","url_validation":"PASS","delivery_enabled":False,"network_calls":0}))
def main():
 p=argparse.ArgumentParser()
 p.add_argument("mode",choices=["selftest","once","status"])
 p.add_argument("--db",default=str(DEFAULT_DB));p.add_argument("--inbox",default=str(DEFAULT_INBOX))
 a=p.parse_args()
 if a.mode=="selftest":selftest();return
 if a.mode=="once":print(json.dumps(once(pathlib.Path(a.db),pathlib.Path(a.inbox)),ensure_ascii=False));return
 path=pathlib.Path(a.db)
 if not path.is_file():raise ValueError("db_missing")
 with sqlite3.connect("file:"+str(path)+"?mode=ro",uri=True) as db:
  count=db.execute("SELECT count(*) FROM events WHERE kind='news_candidate'").fetchone()[0]
 print(json.dumps({"status":"LOCAL_INGEST_STATUS","news_candidates":count,"inbox_exists":pathlib.Path(a.inbox).is_file(),"telegram_sends":0}))
if __name__=="__main__":
 try:main()
 except Exception as exc:
  print(json.dumps({"status":"BLOCKED","reason":type(exc).__name__,"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
