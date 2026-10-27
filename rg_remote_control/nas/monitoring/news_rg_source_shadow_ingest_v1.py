#!/usr/bin/env python3
"""NEWS RG Telegram-source ingestion into ISOLATED shadow DB (Python 3.8+).

No Telegram Bot API, no getUpdates, no public/private messages, no AI requests.
A "scan" only stores recent original Telegram posts in its own isolated DB;
"manual" imports one explicit public t.me link for later editorial processing.
The existing news.sqlite3, callback, bot poller and DSM task are never changed.
"""
import concurrent.futures
import datetime as dt
import hashlib
import html
import json
import os
import pathlib
import re
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request

BASE=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
STORE=BASE/"operator/news_rg_editorial_shadow_v1.sqlite3"
SOURCE_CHANNELS=(
    "tucha888","brosok_mangusta","kyivoperat","gruntmedia",
    "volodymyrzolkin","nexta_live","u_now","insiderUKR",
    "oprichniksday","polit1humor","pezduzalive","eshkinkrot",
    "gistapapapa","OstanniyCapitalist","UaOnlii","lachentyt",
    "ssternenko","Ateobreaking","supernova_plus")
BLOCK_AD=("казино","промокод","букмек","розіграш","розыгрыш",
          "ставки на спорт","на правах реклами","партнерський матеріал")
FOUR_HOURS=4*3600
POST=re.compile(r'data-post="([A-Za-z0-9_]{4,})/([0-9]{1,15})"',re.I)
BODY=re.compile(r'<div\s+class="[^"]*tgme_widget_message_text[^"]*"[^>]*>([\s\S]*?)</div>',re.I)
TIME=re.compile(r'<time\b[^>]*\bdatetime="([^"]+)"',re.I)
PHOTO=re.compile(r'<[^>]+class="[^"]*tgme_widget_message_photo_wrap[^"]*"[^>]*>',re.I)
PHOTO_URL=re.compile(r"background-image\s*:\s*url\((?:'([^']+)'|\"([^\"]+)\"|&quot;([^&]+)&quot;)\)",re.I)
VIDEOS=re.compile(r'<video\b|tgme_widget_message_video\b',re.I)
LINK=re.compile(r"^https://(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z0-9_]{4,})/(\d{1,15})(?:\?single)?$",re.I)

def plain(fragment):
    fragment=re.sub(r"(?i)<br\s*/?>","\n",fragment)
    fragment=re.sub(r"<[^>]+>"," ",fragment)
    return html.unescape(re.sub(r"\s+"," ",fragment)).strip()

def parse_page(page,channel):
    matches=list(POST.finditer(page))
    items=[]
    for i,m in enumerate(matches):
        if m.group(1).lower()!=channel.lower():continue
        piece=page[m.start():matches[i+1].start() if i+1<len(matches) else len(page)]
        if VIDEOS.search(piece):continue
        body=BODY.search(piece)
        if not body:continue
        text=plain(body.group(1))
        if len(text)<50:continue
        photo_tag=PHOTO.search(piece)
        media=PHOTO_URL.search(photo_tag.group(0)) if photo_tag else None
        image=html.unescape(next((x for x in media.groups() if x), "")) if media else ""
        stamp=TIME.search(piece)
        published=html.unescape(stamp.group(1)) if stamp else ""
        items.append({"channel":channel,"number":int(m.group(2)),
                      "text":text,"photo_url":image,"published":published})
    return items

def pub_epoch(raw):
    try:
        d=dt.datetime.fromisoformat(raw.replace("Z","+00:00"))
        if d.tzinfo is None:d=d.replace(tzinfo=dt.timezone.utc)
        return d.timestamp()
    except (ValueError,TypeError,AttributeError):return None

def fetch(channel,before=None,loader=None):
    if loader is not None:return loader(channel,before)
    url="https://t.me/s/"+channel
    if before is not None:url+="?before="+str(before)
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0",
                             "Accept-Language":"uk,en;q=0.8"})
    with urllib.request.urlopen(req,timeout=8) as res:
        if res.status!=200:raise ValueError("PUBLIC_SOURCE_NOT_OK")
        return res.read(900000).decode("utf-8","replace")

def init(cx):
    cx.executescript("""CREATE TABLE IF NOT EXISTS source_cursor(
        channel TEXT PRIMARY KEY, highest INTEGER NOT NULL,
        initialized_at INTEGER NOT NULL, last_scan_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS story_shadow(
        key TEXT PRIMARY KEY,channel TEXT NOT NULL,number INTEGER NOT NULL,
        posted_at INTEGER, text TEXT NOT NULL, photo_url TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status='needs_editorial_rewrite'),
        origin TEXT NOT NULL CHECK(origin IN ('approved_source','manual_link')),
        queued_at INTEGER NOT NULL,
        UNIQUE(channel,number));""")

def db_connection(store):
    store.parent.mkdir(parents=True,exist_ok=True)
    if store.is_symlink():raise ValueError("SHADOW_DB_SYMLINK")
    created=not store.exists()
    cx=sqlite3.connect(str(store),isolation_level=None,timeout=8)
    cx.execute("PRAGMA busy_timeout=8000")
    if created:os.chmod(str(store),0o600)
    init(cx)
    return cx

def story_status(raw,now,manual=False):
    epoch=pub_epoch(raw.get("published"))
    if epoch is None or now-epoch>FOUR_HOURS or epoch>now+300:
        return "stale_or_unverified_timestamp"
    text=raw.get("text") or ""
    if len(text)<65 or any(x in text.lower() for x in BLOCK_AD):
        return "brief_or_advertisement"
    image=raw.get("photo_url") or ""
    if not image.startswith("https://") or len(image)>2048:
        return "missing_real_photo"
    return "eligible_for_editorial"

def scan_once(store=STORE,now=None,channels=SOURCE_CHANNELS,loader=None):
    now=int(time.time()) if now is None else int(now)
    if not isinstance(channels,(tuple,list)) or any(c not in SOURCE_CHANNELS for c in channels):
        raise ValueError("SOURCE_LIST_NOT_APPROVED")
    cx=db_connection(store)
    try:
        old={c:n for c,n in cx.execute("SELECT channel,highest FROM source_cursor")}
        def load(channel):
            try:return channel,parse_page(fetch(channel,loader=loader),channel),None
            except (urllib.error.URLError,urllib.error.HTTPError,TimeoutError,OSError,ValueError):
                return channel,[], "fetch_failed"
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            batches=list(pool.map(load,channels))
        status={"schema":"NEWS_RG_SOURCE_SHADOW_INGEST_V1",
                "source_count":len(channels),"initialized_sources":0,
                "new_stories_staged_for_editorial":0,
                "media_missing_skipped":0,"old_or_short_skipped":0,
                "failed_sources":0,"duplicates":0,
                "telegram_bot_api_calls":0,"private_sends":0,
                "publications":0,"pollers_started":0}
        cx.execute("BEGIN IMMEDIATE")
        try:
            for channel,posts,error in batches:
                if error:
                    status["failed_sources"]+=1
                    continue
                high=max((x["number"] for x in posts),default=old.get(channel,0))
                if channel not in old:
                    # First observation is only a high-water mark: no backfill.
                    cx.execute("INSERT INTO source_cursor VALUES(?,?,?,?)",
                               (channel,high,now,now))
                    status["initialized_sources"]+=1
                    continue
                last=old[channel]
                for post in posts:
                    if post["number"]<=last:continue
                    reason=story_status(post,now)
                    if reason!="eligible_for_editorial":
                        stat="media_missing_skipped" if reason=="missing_real_photo" \
                                  else "old_or_short_skipped"
                        status[stat]+=1
                        continue
                    key=hashlib.sha256((channel.lower()+":"+str(post["number"])).encode()).hexdigest()[:24]
                    stamp=int(pub_epoch(post["published"]))
                    result=cx.execute("INSERT OR IGNORE INTO story_shadow VALUES(?,?,?,?,?,?,?,?,?)",
                        (key,channel,post["number"],stamp,post["text"],
                         post["photo_url"],"needs_editorial_rewrite",
                         "approved_source",now))
                    if result.rowcount:
                        status["new_stories_staged_for_editorial"]+=1
                    else:status["duplicates"]+=1
                cx.execute("UPDATE source_cursor SET highest=?,last_scan_at=? WHERE channel=?",
                           (max(last,high),now,channel))
            # This is a bounded shadow staging area, never a moderation queue.
            cx.execute("DELETE FROM story_shadow WHERE queued_at<?",(now-3*86400,))
            cx.execute("COMMIT")
        except Exception:
            cx.execute("ROLLBACK")
            raise
        status["shadow_pending_rewrites"]=cx.execute(
            "SELECT COUNT(*) FROM story_shadow WHERE status='needs_editorial_rewrite'"
        ).fetchone()[0]
        return status
    finally:cx.close()

def import_manual(link,store=STORE,now=None,loader=None):
    now=int(time.time()) if now is None else int(now)
    if not isinstance(link,str):raise ValueError("LINK_REQUIRED")
    m=LINK.fullmatch(link.strip())
    if not m or m.group(1).lower() in ("joinchat","private","c") or \
            int(m.group(2))<1:
        raise ValueError("PUBLIC_POST_LINK_REQUIRED")
    channel,number=m.group(1),int(m.group(2))
    posts=parse_page(fetch(channel,before=number+1,loader=loader),channel)
    found=next((x for x in posts if x["number"]==number),None)
    if not found:raise ValueError("REQUESTED_POST_NOT_VISIBLE")
    reason=story_status(found,now,manual=True)
    if reason!="eligible_for_editorial":
        return {"status":"MANUAL_STORY_NOT_READY","reason":reason,
                "telegram_bot_api_calls":0,"publications":0}
    cx=db_connection(store)
    try:
        key=hashlib.sha256((channel.lower()+":"+str(number)).encode()).hexdigest()[:24]
        stamp=int(pub_epoch(found["published"]))
        cursor=cx.execute("INSERT OR IGNORE INTO story_shadow VALUES(?,?,?,?,?,?,?,?,?)",
                          (key,channel,number,stamp,found["text"],found["photo_url"],
                           "needs_editorial_rewrite","manual_link",now))
        return {"status":"MANUAL_STAGED_FOR_EDITORIAL" if cursor.rowcount else "DUPLICATE",
                "telegram_bot_api_calls":0,"publications":0,
                "text_not_sent_to_moderation_yet":True}
    finally:cx.close()

def selftest():
    now=dt.datetime(2026,10,27,11,tzinfo=dt.timezone.utc).timestamp()
    date=dt.datetime.fromtimestamp(now-100,dt.timezone.utc).isoformat()
    def msg(n,channel="Ateobreaking"):
        return ('<div class="tgme_widget_message js-widget_message" data-post="'
          +channel+"/"+str(n)+'"><div class="tgme_widget_message_text js-message_text">'
          +"Важливе повідомлення про подію, яке редактор перевірить перед публікацією. "
          +'</div><a class="tgme_widget_message_photo_wrap" '
          +'style="background-image:url(&quot;https://cdn.test/photo.jpg&quot;)"></a>'
          +'<time datetime="'+date+'">now</time></div>')
    def loader(channel,before):
        return msg(12,channel) if before is None else msg(before-1,channel)
    posts=parse_page(msg(12),"Ateobreaking")
    assert len(posts)==1 and posts[0]["photo_url"].startswith("https://")
    with tempfile.TemporaryDirectory() as td:
        store=pathlib.Path(td)/"shadows/db.sqlite3"
        a=scan_once(store,int(now),("Ateobreaking",),loader)
        assert a["initialized_sources"]==1 and a["new_stories_staged_for_editorial"]==0
        def next_loader(channel,before):return msg(13,channel)
        b=scan_once(store,int(now)+1,("Ateobreaking",),next_loader)
        assert b["new_stories_staged_for_editorial"]==1,b
        c=scan_once(store,int(now)+2,("Ateobreaking",),next_loader)
        assert c["new_stories_staged_for_editorial"]==0
        m=import_manual("https://t.me/otherpublic/17",store,int(now),loader)
        assert m["status"]=="MANUAL_STAGED_FOR_EDITORIAL",m
        cx=sqlite3.connect(str(store))
        assert cx.execute("SELECT COUNT(*) FROM story_shadow").fetchone()[0]==2
        cx.close()
    print("NEWS_RG_SOURCE_SHADOW_INGEST_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["scan"]:
        print(json.dumps(scan_once(),sort_keys=True,ensure_ascii=False,indent=2))
    elif len(sys.argv)==3 and sys.argv[1]=="manual":
        print(json.dumps(import_manual(sys.argv[2]),sort_keys=True,ensure_ascii=False,indent=2))
    else:raise SystemExit("Only selftest, scan and manual URL supported")
