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
def parse(raw):
 if len(raw)>MAX_FETCH or b"<!DOCTYPE" in raw.upper():raise ValueError("rss_invalid_size_or_dtd")
 root=ET.fromstring(raw)
 nodes=root.findall("./channel/item")
 if not nodes:
  nodes=root.findall(".//{http://www.w3.org/2005/Atom}entry")
 result=[];seen=set();missing=0
 for item in nodes[:45]:
  title=" ".join((item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or "").split())
  link=item.findtext("link") or ""
  if not link:
   for el in item.findall("{http://www.w3.org/2005/Atom}link"):
    if el.attrib.get("rel","alternate")=="alternate":link=el.attrib.get("href","");break
  img=first_image(item)
  if not 18<=len(title)<=400 or not safe_https(link):continue
  if not img:missing+=1;continue
  cid=hashlib.sha256(link.encode("utf-8")).hexdigest()[:12]
  if cid in seen:continue
  seen.add(cid)
  result.append({"candidate_id":cid,"headline":title,"source_url":link,"image_url":img,"detected_at":0})
 return result,missing
def scan(feeds,output):
 rows=[];errors=[];missing=0;seen=set()
 for url in feeds:
  try:
   req=urllib.request.Request(url,headers={"User-Agent":"RG-News-NAS-Shadow/1.0","Accept":"application/rss+xml,application/xml,text/xml"})
   with urllib.request.urlopen(req,timeout=15) as r:
    if r.status!=200:raise ValueError("rss_http_status")
    raw=r.read(MAX_FETCH+1)
   items,n=parse(raw);missing+=n
   for item in items:
    if item["candidate_id"] not in seen:
     seen.add(item["candidate_id"]);rows.append(item)
  except Exception as exc:errors.append({"host":urlsplit(url).hostname,"reason":type(exc).__name__})
 if not rows:
  print(json.dumps({"status":"RSS_NO_NEW_CANDIDATES","feeds":len(feeds),"errors":errors,"missing_images":missing,"telegram_sends":0}))
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
 print(json.dumps({"status":"RSS_SHADOW_SPOOLED","candidates":len(rows),"missing_images":missing,"errors":errors,"cloudflare_calls":0,"telegram_sends":0},ensure_ascii=False))
 return 0
def selftest():
 doc=b"""<?xml version="1.0" encoding="utf-8"?><rss xmlns:media="http://search.yahoo.com/mrss/" version="2.0"><channel>
 <item><title>Important Ukrainian headline number one</title><link>https://example.org/n1</link><media:content url="https://example.org/n1.jpg" type="image/jpeg"/></item>
 <item><title>News without any illustration at all</title><link>https://example.org/n2</link></item>
 </channel></rss>"""
 rows,missing=parse(doc)
 assert len(rows)==1 and missing==1 and rows[0]["candidate_id"]==hashlib.sha256(b"https://example.org/n1").hexdigest()[:12]
 assert safe_https("https://example.org/image.jpg")
 assert not safe_https("http://example.org/image.jpg")
 assert not safe_https("https://user:pass@example.org/image.jpg")
 try:parse(b"<!DOCTYPE foo><rss></rss>")
 except ValueError:pass
 else:raise AssertionError("DTD accepted")
 print(json.dumps({"selftest":"PASS","mandatory_image":"PASS","rss_parser":"PASS","stable_candidate_ids":"PASS","telegram_sends":0,"cloudflare_calls":0}))
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
