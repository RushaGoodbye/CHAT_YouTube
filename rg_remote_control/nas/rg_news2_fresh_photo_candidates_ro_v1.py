#!/usr/bin/env python3
"""Read-only News2 fresh photo candidate inspection; no Telegram API or database writes."""
import json,sqlite3,pathlib,urllib.parse,datetime
DB=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2/news.sqlite3")
def main():
    uri="file:"+urllib.parse.quote(str(DB),safe="/")+"?mode=ro"
    with sqlite3.connect(uri,uri=True,timeout=5) as db:
        db.row_factory=sqlite3.Row
        columns={r[1] for r in db.execute("PRAGMA table_info(candidates)")}
        required={"id","status","photo_url","photo_reviewed","created_at"}
        if not required.issubset(columns):
            print(json.dumps({"status":"BLOCKED_SCHEMA","missing":sorted(required-columns)}));return
        display=[x for x in ("id","created_at","status","photo_url","source_url","title","caption","photo_reviewed") if x in columns]
        rows=db.execute("SELECT "+",".join(display)+" FROM candidates WHERE status='awaiting_photo_review' ORDER BY created_at DESC LIMIT 8").fetchall()
        out=[]
        for r in rows:
            item=dict(r)
            for key in ("title","caption"):
                if key in item and item[key] is not None:item[key]=str(item[key])[:240]
            out.append(item)
    print(json.dumps({"status":"NEWS2_FRESH_PHOTO_REVIEW_CANDIDATES","read_only":True,"count":len(out),"items":out},ensure_ascii=False))
if __name__=="__main__":main()
