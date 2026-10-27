#!/usr/bin/env python3
"""Read-only NEWS RG feed/transport probe, Python 3.8+.

Checks t.me/s for the 19 approved sources (public HTTP only).
Inspects NAS operator module names and AST markers without importing/running them.
No Telegram Bot API, getUpdates, writes, SQL changes, publication, or poller.
Never prints raw posts, URLs, tokens, chat IDs or imported content.
"""
import concurrent.futures
import datetime as dt
import html.parser
import json
import pathlib
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
CHANNELS=("tucha888","brosok_mangusta","kyivoperat","gruntmedia",
"volodymyrzolkin","nexta_live","u_now","insiderUKR","oprichniksday",
"polit1humor","pezduzalive","eshkinkrot","gistapapapa","OstanniyCapitalist",
"UaOnlii","lachentyt","ssternenko","Ateobreaking","supernova_plus")
PRIORITY={"tucha888","brosok_mangusta","kyivoperat","nexta_live",
"u_now","insiderUKR","ssternenko","Ateobreaking","supernova_plus"}

class PublicPosts(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.posts=[]
        self.current=None
        self.depth=0
        self.text_at=None
        self.time_at=None
    def handle_starttag(self,tag,attr):
        attrs=dict(attr)
        classes=attrs.get("class","")
        if tag=="div" and "data-post" in attrs and \
                re.fullmatch(r"[A-Za-z0-9_]+/\d+",attrs["data-post"] or ""):
            self.current={"post":attrs["data-post"],"text":"","photo":False,
                          "video":False,"date":None}
            self.depth=1
            self.text_at=None
            return
        if self.current is None:return
        if tag=="div":self.depth+=1
        if "tgme_widget_message_text" in classes:
            self.text_at=self.depth
        if "tgme_widget_message_photo_wrap" in classes:
            self.current["photo"]=True
        if "tgme_widget_message_video" in classes:
            self.current["video"]=True
        if tag=="time" and "datetime" in attrs:
            self.current["date"]=attrs["datetime"]
    def handle_data(self,data):
        if self.current is not None and self.text_at is not None:
            self.current["text"]+=data+" "
    def handle_endtag(self,tag):
        if self.current is None:return
        if tag=="div":
            if self.text_at==self.depth:self.text_at=None
            self.depth-=1
            if self.depth==0:
                self.posts.append(self.current)
                self.current=None
                self.text_at=None

def classify_pub(post,now=None):
    now=now or time.time()
    text=" ".join(str(post.get("text") or "").split())
    age=None
    try:
        d=dt.datetime.fromisoformat(str(post.get("date")).replace("Z","+00:00"))
        if d.tzinfo is None:d=d.replace(tzinfo=dt.timezone.utc)
        age=(now-d.timestamp())/3600.0
    except (TypeError,ValueError,OverflowError):pass
    return {"has_photo":bool(post.get("photo")),"has_video":bool(post.get("video")),
            "text_chars":len(text),"dated":age is not None,
            "recent_4h":age is not None and -0.1<=age<=4,
            "old_or_undated":age is None or age>4}

def inspect_channel(channel,loader=None):
    if loader is None:
        def loader(name):
            req=urllib.request.Request("https://t.me/s/"+name,
                 headers={"User-Agent":"Mozilla/5.0 NEWSRG/1.0",
                          "Accept-Language":"uk,en;q=0.8"})
            with urllib.request.urlopen(req,timeout=6) as response:
                if response.status!=200:return response.status,b""
                content=response.read(850000)
                return response.status,content
    try:
        status,raw=loader(channel)
        if status!=200:
            return {"source":"@"+channel,"status":"HTTP_"+str(status),
                    "priority":channel in PRIORITY}
        parser=PublicPosts()
        parser.feed(raw.decode("utf-8","replace"))
        props=[classify_pub(p) for p in parser.posts]
        return {"source":"@"+channel,"status":"OK" if parser.posts else "NO_PUBLIC_POSTS",
                "priority":channel in PRIORITY,
                "posts_seen":len(props),
                "posts_recent_4h":sum(x["recent_4h"] for x in props),
                "recent_with_photo":sum(x["recent_4h"] and x["has_photo"] for x in props),
                "recent_with_video":sum(x["recent_4h"] and x["has_video"] for x in props),
                "recent_text_ge_100":sum(x["recent_4h"] and x["text_chars"]>=100
                                          for x in props)}
    except urllib.error.HTTPError as e:
        return {"source":"@"+channel,"status":"HTTP_"+str(e.code),
                "priority":channel in PRIORITY}
    except (urllib.error.URLError,TimeoutError,OSError,ValueError):
        return {"source":"@"+channel,"status":"REQUEST_FAILED",
                "priority":channel in PRIORITY}

def local_hints(root=ROOT):
    paths={
      "main_bot":"rg_v18.py",
      "private_photo_sender":"telegram_photo_review_flow.py",
      "outbound_queue":"operator/rg_news2_outbound_queue_v2.py",
      "rss_ingest":"operator/rg_news2_rss_hourly.py",
      "native_callback":"operator/rg_news2_p31_guarded_callback_once.py",
      "telegram_text_ingest":"operator/rg_news2_telegram_sources_v1.py",
      "editorial_rewriter":"operator/rg_news2_text_editorial_v1.py",
      "telegram_link_import":"operator/rg_news2_manual_link_import_v1.py"
    }
    out={}
    for key,relative in paths.items():
        path=root/relative
        if path.is_symlink() or not path.is_file() or path.stat().st_size>750000:
            out[key]={"exists":False}
            continue
        content=path.read_text(encoding="utf-8",errors="replace").lower()
        out[key]={"exists":True}
        if key in ("main_bot","native_callback","outbound_queue","private_photo_sender"):
            out[key].update({
              "uses_bot_getupdates":"getupdates" in content or "get_updates" in content,
              "mentions_manual_link_pattern":"t.me/" in content or
                      "telegram.me/" in content,
              "has_gemini_integration":"gemini" in content or
                      "generativelanguage.googleapis.com" in content,
              "has_openai_integration":"api.openai.com" in content or
                      "openai_api_key" in content,
              "mentions_text_editorial":"text_editorial" in content or
                      "rewrit" in content or "перепиш" in content
            })
    return out

def run(root=ROOT,network=True,channels=CHANNELS,loader=None):
    result={"schema":"NEWS_RG_SOURCE_PIPELINE_PROBE_V1",
            "read_only":True,"telegram_bot_api_calls":0,
            "no_get_updates":True,"writes":0,"publications":0,
            "pollers_started":0,
            "approved_channel_count":len(CHANNELS),
            "existing_modules":local_hints(root)}
    if network:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            outcome=list(pool.map(lambda c:inspect_channel(c,loader),channels))
        result["public_telegram_feed"]={"tested":len(outcome),
          "ok":sum(x["status"]=="OK" for x in outcome),
          "recent_posts":sum(x.get("posts_recent_4h",0) for x in outcome),
          "recent_photo_posts":sum(x.get("recent_with_photo",0) for x in outcome),
          "results":outcome}
    else:
        result["public_telegram_feed"]={"tested":0}
    result["next_step"]="Require editorial provider and current inbound callback contract before any live integration."
    return result

def selftest():
    test_html='''<div class="tgme_widget_message js-widget_message" data-post="Ateobreaking/123">
<div class="tgme_widget_message_text js-message_text" dir="auto">Важлива новина для тестування <b>повідомлення</b>.</div>
<div class="tgme_widget_message_photo_wrap" style="background-image:url('ignored')"></div>
<time datetime="2026-10-27T10:00:00+00:00">10:00</time></div>'''
    p=PublicPosts();p.feed(test_html)
    assert len(p.posts)==1
    assert p.posts[0]["photo"]
    assert "повідомлення" in p.posts[0]["text"]
    x=inspect_channel("Ateobreaking",lambda _: (200,test_html.encode()))
    assert x["posts_seen"]==1 and x["status"]=="OK" and x["priority"]
    z=inspect_channel("Ateobreaking",lambda _: (403,b""))
    assert z["status"]=="HTTP_403"
    with tempfile.TemporaryDirectory() as td:
        r=run(pathlib.Path(td),True,("Ateobreaking",),
              lambda _: (200,test_html.encode()))
        s=json.dumps(r)
        assert "ignored" not in s and "Важлива" not in s
        assert r["telegram_bot_api_calls"]==0 and r["writes"]==0
    print("NEWS_RG_SOURCE_PIPELINE_PROBE_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["inspect"]:
        print(json.dumps(run(),ensure_ascii=False,sort_keys=True,indent=2))
    elif sys.argv[1:]==["inspect-local"]:
        print(json.dumps(run(network=False),ensure_ascii=False,sort_keys=True,indent=2))
    else:raise SystemExit("Only selftest, inspect and inspect-local supported")
