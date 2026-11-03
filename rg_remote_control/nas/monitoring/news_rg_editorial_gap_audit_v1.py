#!/usr/bin/env python3
"""NEWS RG editorial-chain read-only audit. No Telegram/API/network, no writes.
Summarizes news sources, original content length and real image availability.
No raw text, URLs, identifiers, config secrets or Telegram chat IDs emitted.
Python 3.8+.
"""
import collections
import datetime as dt
import json
import pathlib
import re
import sqlite3
import sys
import tempfile
import time

ROOT=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
SOURCES=("tucha888","brosok_mangusta","kyivoperat","gruntmedia",
 "volodymyrzolkin","nexta_live","u_now","insiderUKR","oprichniksday",
 "polit1humor","pezduzalive","eshkinkrot","gistapapapa","OstanniyCapitalist",
 "UaOnlii","lachentyt","ssternenko","Ateobreaking","supernova_plus")
FIELDS=("source","status","caption","photo_url","image_url","body",
        "text","source_url","created_at","updated_at")

def classify_source(value):
    if not isinstance(value,str) or not value:return "missing"
    raw=value.strip().lower().strip("@")
    for name in SOURCES:
        if raw==name.lower() or re.search(r"(?i)(?:^|[/@])"+
                      re.escape(name)+r"(?:$|[/?:#])",value):
            return "@"+name
    if "rss" in raw:return "rss_or_feed"
    if "manual" in raw or "import" in raw:return "manual_or_import"
    if "telegram" in raw or "t.me" in raw:return "other_telegram_source"
    return "other_unmapped_source"

def media_kind(raw):
    if not isinstance(raw,str) or not raw.strip():return "missing"
    if raw.startswith(("https://","http://")):return "remote_url_unverified"
    if raw.startswith(("tg://","telegram:")):return "telegram_media_reference"
    if raw.startswith(("/volume","/var","file:")):return "local_reference"
    return "other_unverified"

def text_size(value):
    if not isinstance(value,str) or not value.strip():return "missing"
    n=len(value.strip())
    return "short_under_100" if n<100 else "100_to_499" if n<500 else (
            "500_to_1000" if n<=1000 else "over_1000")

def age_minutes(raw):
    try:
        if isinstance(raw,(float,int)):
            stamp=float(raw)/1000 if raw>1e12 else float(raw)
        else:
            d=dt.datetime.fromisoformat(raw.replace("Z","+00:00"))
            if d.tzinfo is None:d=d.replace(tzinfo=dt.timezone.utc)
            stamp=d.timestamp()
        if 946684800<stamp<4102444800:
            return round(max(0,time.time()-stamp)/60,1)
    except (ValueError,TypeError,OverflowError,AttributeError):pass
    return None

def inspect(root=ROOT):
    db=root/"news.sqlite3"
    if not db.is_file() or db.is_symlink():
        raise RuntimeError("DATABASE_NOT_REGULAR")
    cx=sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)
    cx.execute("PRAGMA query_only=ON")
    try:
        cols={r[1] for r in cx.execute('PRAGMA table_info("candidates")')}
        if not {"source","status","caption"}.issubset(cols):
            raise RuntimeError("CANDIDATE_SCHEMA_UNKNOWN")
        selected=[x for x in FIELDS if x in cols]
        records=[dict(zip(selected,r)) for r in cx.execute(
            "SELECT "+",".join('"'+x+'"' for x in selected)+
            " FROM candidates ORDER BY rowid DESC LIMIT 1200")]
        total=cx.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        by_source=collections.Counter(classify_source(x.get("source")) for x in records)
        waiting=[x for x in records if x.get("status")=="awaiting_photo_review"]
        photo_field="photo_url" if "photo_url" in cols else (
                    "image_url" if "image_url" in cols else None)
        by_text=dict(sorted(collections.Counter(text_size(x.get("caption"))
                          for x in waiting).items()))
        by_media=dict(sorted(collections.Counter(media_kind(x.get(photo_field))
                           for x in waiting).items())) if photo_field else {}
        modules={
          "photo_flow":root/"telegram_photo_review_flow.py",
          "private_dispatch_guard":root/"rg_news2_private_final_guard_v1.py",
          "photo_outbound":root/"operator/rg_news2_outbound_queue_v2.py",
          "rss_ingest":root/"operator/rg_news2_rss_hourly.py",
          "main_bot":root/"rg_v18.py",
          "scheduled_tick":root/"rg_news_dsm_tick.sh",
          "editorial_worker":root/"operator/rg_news2_text_editorial_v1.py"}
        match={k:v for k,v in sorted(by_source.items()) if k.startswith("@")}
        return {
          "schema":"NEWS_RG_EDITORIAL_GAP_AUDIT_V1","read_only":True,
          "telegram_calls":0,"network_calls":0,"sqlite_writes":0,
          "pollers_started":0,"publications":0,
          "approved_source_count":len(SOURCES),
          "approved_source_candidate_matches":match,
          "approved_source_matched_rows":sum(match.values()),
          "unmapped_source_categories":{
             k:v for k,v in sorted(by_source.items()) if not k.startswith("@")},
          "sampled_candidate_rows":len(records),
          "total_candidates":total,
          "sampled_statuses":dict(sorted(collections.Counter(
                                 str(x.get("status")) for x in records).items())),
          "queued_photo_review_rows":len(waiting),
          "queued_caption_length_classes":by_text,
          "queued_media_classes":by_media,
          "queued_captions_with_links":sum(bool(re.search(
              r"(?i)(?:https?://|www[.]|t[.]me/)",x.get("caption") or ""))
              for x in waiting),
          "last_twelve_queue_caption_shapes":[text_size(x.get("caption"))
                        for x in waiting[:12]],
          "last_twelve_queue_media_types":[media_kind(x.get(photo_field))
                        for x in waiting[:12]] if photo_field else [],
          "newest_candidate_age_minutes":age_minutes(records[0].get("created_at"))
                        if records else None,
          "installed_components":{k:(p.is_file() and not p.is_symlink())
                           for k,p in modules.items()},
          "auto_editorial_rewrite_proven":False,
          "manual_link_import_proven":False,
          "caveat":"Matches classify candidate.source only; absent match is not proof source not scanned."}
    finally:cx.close()

def selftest():
    with tempfile.TemporaryDirectory() as td:
        root=pathlib.Path(td)
        cx=sqlite3.connect(str(root/"news.sqlite3"))
        cx.execute("CREATE TABLE candidates(source TEXT,status TEXT,caption TEXT,photo_url TEXT,created_at TEXT)")
        cx.executemany("INSERT INTO candidates VALUES(?,?,?,?,?)",[
            ("@Ateobreaking","awaiting_photo_review","x"*530,
             "https://example.org/real.jpg",None),
            ("rss_hourly","awaiting_photo_review","bad https://spam.invalid","",None),
            ("@supernova_plus","awaiting_moderation","x"*150,"tg://photo",None),
            ("token secret","awaiting_photo_review","PRIVATE_TOKEN_SHOULD_NOT_LEAK",
             "file:/tmp/example.jpg",None)])
        cx.commit();cx.close()
        r=inspect(root)
        assert r["approved_source_matched_rows"]==2
        assert r["queued_photo_review_rows"]==3
        assert r["queued_caption_length_classes"]["500_to_1000"]==1
        assert r["queued_media_classes"]["missing"]==1
        assert r["queued_captions_with_links"]==1
        output=json.dumps(r)
        assert "PRIVATE_TOKEN_SHOULD_NOT_LEAK" not in output
        assert "token secret" not in output
    print("NEWS_RG_EDITORIAL_GAP_AUDIT_SELFTEST_PASS")

if __name__=="__main__":
    if sys.argv[1:]==["selftest"]:selftest()
    elif sys.argv[1:]==["inspect"]:
        print(json.dumps(inspect(),indent=2,sort_keys=True,ensure_ascii=False))
    else:sys.exit("Only selftest or inspect supported")
