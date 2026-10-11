#!/usr/bin/env python3
"""NAS local RSS news sampler, shadow spool only. No Telegram, AI, Cloudflare.
Uses official public news RSS feeds; image is mandatory. No auto-publication.
"""
import argparse,email.utils,hashlib,html,json,os,pathlib,re,sys,tempfile,time,urllib.request,xml.etree.ElementTree as ET
from urllib.parse import urlsplit
STATE=pathlib.Path("/volume1/docker/RG_TELEGRAM_STATE")
INBOX=STATE/"candidate_inbox.jsonl"
FEEDS=("https://www.pravda.com.ua/rss/view_news/","https://www.ukrinform.ua/rss/block-lastnews")
MEDIA="{http://search.yahoo.com/mrss/}"
ENC="{http://purl.org/rss/1.0/modules/content/}"
MAX_FETCH=1250000
MAX_AGE_SEC=36*3600
MAX_FUTURE_SEC=5*60
def safe_https(u):
 try:
  p=urlsplit(u)
  return p.scheme=="https" and bool(p.hostname) and not p.username and not p.password and not p.fragment and p.port in (None,443) and len(u)<=1800
 except (TypeError,ValueError):return False
def first_image(item):
 # Only explicit image enclosures/media. Do not publish decorative page images.
 for tag in (MEDIA+"content",MEDIA+"thumbnail","enclosure"):
  for element in item.iter(tag):
   u=element.attrib.get("url","")
   kind=element.attrib.get("type","")
   if tag=="enclosure" and kind and not kind.startswith("image/"):continue
   if safe_https(u):return u
 for tag in (ENC+"encoded","description"):
  node=item.find(tag)
  if node is not None and node.text:
   match=re.search(r'<img\b[^>]*\bsrc=["\'](https://[^"\']+)["\']',html.unescape(node.text),re.I)
   if match and safe_https(match.group(1)):return match.group(1)
 return None
def published_epoch(item):
 raw=(item.findtext("pubDate") or item.findtext("{http://www.w3.org/2005/Atom}published") or item.findtext("{http://www.w3.org/2005/Atom}updated") or "").strip()
 if not raw:return None
 try:
  if "T" in raw:
   import datetime
   dt=datetime.datetime.fromisoformat(raw.replace("Z","+00:00"))
  else:
   dt=email.utils.parsedate_to_datetime(raw)
  if dt.tzinfo is None:return None
  return int(dt.timestamp())
 except (TypeError,ValueError,OverflowError):return None
def parse(raw,now=None):
 if len(raw)>MAX_FETCH or b"<!DOCTYPE" in raw.upper():raise ValueError("rss_invalid_size_or_dtd")
 root=ET.fromstring(raw)
 nodes=root.findall("./channel/item")
 if not nodes:
  nodes=root.findall(".//{http://www.w3.org/2005/Atom}entry")
 result=[];seen=set();missing=0;stale=0;undated=0
 if now is None:now=int(time.time())
 for item in nodes[:45]:
  title=" ".join((item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or "").split())
  link=item.findtext("link") or ""
  if not link:
   for el in item.findall("{http://www.w3.org/2005/Atom}link"):
    if el.attrib.get("rel","alternate")=="alternate":link=el.attrib.get("href","");break
  img=first_image(item)
  if not 18<=len(title)<=400 or not safe_https(link):continue
  published=published_epoch(item)
  if published is None:undated+=1;continue
  if published<now-MAX_AGE_SEC or published>now+MAX_FUTURE_SEC:stale+=1;continue
  if not img:missing+=1;continue
  cid=hashlib.sha256(link.encode("utf-8")).hexdigest()[:12]
  if cid in seen:continue
  seen.add(cid)
  result.append({"candidate_id":cid,"headline":title,"source_url":link,"image_url":img,"detected_at":published})
 return result,{"missing_images":missing,"stale_or_future":stale,"undated":undated}
def scan(feeds,output):
 rows=[];errors=[];missing=0;stale=0;undated=0;seen=set()
 for url in feeds:
  try:
   req=urllib.request.Request(url,headers={"User-Agent":"RG-News-NAS-Shadow/1.0","Accept":"application/rss+xml,application/xml,text/xml"})
   with urllib.request.urlopen(req,timeout=15) as r:
    if r.status!=200:raise ValueError("rss_http_status")
    raw=r.read(MAX_FETCH+1)
   items,n=parse(raw);missing+=n["missing_images"];stale+=n["stale_or_future"];undated+=n["undated"]
   for item in items:
    if item["candidate_id"] not in seen:
     seen.add(item["candidate_id"]);rows.append(item)
  except Exception as exc:errors.append({"host":urlsplit(url).hostname,"reason":type(exc).__name__})
 if not rows:
  print(json.dumps({"status":"RSS_NO_NEW_CANDIDATES","feeds":len(feeds),"errors":errors,"missing_images":missing,"stale_or_future":stale,"undated":undated,"telegram_sends":0}))
  return 1
 output.parent.mkdir(parents=True,exist_ok=True)
 content="".join(json.dumps(item,ensure_ascii=False,separators=(",",":"))+"\n" for item in rows)
 if len(content.encode("utf-8"))>2097152:raise ValueError("spool_too_large")
 fd,tmp=tempfile.mkstemp(prefix=".rss-spool-",dir=str(output.parent))
 try:
  with os.fdopen(fd,"w",encoding="utf-8") as f:f.write(content)
  os.chmod(tmp,0o640)
  os.replace(tmp,output)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
 print(json.dumps({"status":"RSS_SHADOW_SPOOLED","candidates":len(rows),"missing_images":missing,"stale_or_future":stale,"undated":undated,"errors":errors,"cloudflare_calls":0,"telegram_sends":0},ensure_ascii=False))
 return 0
def selftest():
 import datetime
 now=1760198400
 stamp=lambda delta:email.utils.format_datetime(datetime.datetime.fromtimestamp(now+delta,datetime.timezone.utc))
 items=[
  ("Fresh valid headline from the current day","https://example.org/n1","https://example.org/n1.jpg",stamp(-900)),
  ("Old headline should be rejected right now","https://example.org/n2","https://example.org/n2.jpg",stamp(-48*3600)),
  ("Headline without any image is excluded","https://example.org/n3","",stamp(-900)),
  ("Headline without publishing date excluded","https://example.org/n4","https://example.org/n4.jpg",""),
  ("Future item should be rejected as suspicious","https://example.org/n5","https://example.org/n5.jpg",stamp(7200))]
 parts=[]
 for title,link,img,date in items:
  media='<media:content url="'+img+'" type="image/jpeg"/>' if img else ""
  date_node="<pubDate>"+date+"</pubDate>" if date else ""
  parts.append("<item><title>"+title+"</title><link>"+link+"</link>"+media+date_node+"</item>")
 doc=('<?xml version="1.0"?><rss xmlns:media="http://search.yahoo.com/mrss/" version="2.0"><channel>'+''.join(parts)+'</channel></rss>').encode()
 rows,stat=parse(doc,now=now)
 assert len(rows)==1 and rows[0]["detected_at"]==now-900,(rows,stat)
 assert stat=={"missing_images":1,"stale_or_future":2,"undated":1},stat
 assert rows[0]["candidate_id"]==hashlib.sha256(b"https://example.org/n1").hexdigest()[:12]
 try:parse(b"<!DOCTYPE x><rss/>")
 except ValueError:pass
 else:raise AssertionError("DTD accepted")
 print(json.dumps({"selftest":"PASS","freshness_gate":"PASS","mandatory_image":"PASS","undated_rejected":"PASS","stable_candidate_ids":"PASS","telegram_sends":0,"cloudflare_calls":0}))
def main():
 p=argparse.ArgumentParser();p.add_argument("mode",choices=["selftest","once","status"])
 p.add_argument("--out",default=str(INBOX));a=p.parse_args()
 if a.mode=="selftest":selftest();return
 if a.mode=="status":
  target=pathlib.Path(a.out)
  print(json.dumps({"status":"RSS_SPOOL_STATUS","exists":target.is_file(),"age_sec":int(time.time()-target.stat().st_mtime) if target.is_file() else None,"telegram_sends":0}));return
 if pathlib.Path(a.out).is_symlink():raise ValueError("spool_symlink")
 sys.exit(scan(FEEDS,pathlib.Path(a.out)))
if __name__=="__main__":
 try:main()
 except Exception as exc:
  print(json.dumps({"status":"BLOCKED","reason":type(exc).__name__,"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
