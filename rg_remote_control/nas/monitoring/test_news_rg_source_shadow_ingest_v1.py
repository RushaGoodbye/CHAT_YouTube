#!/usr/bin/env python3
"""Extended NEWS RG nonpublishing shadow source tests, Python 3.8+."""
import datetime as dt
import importlib.util
import json
import pathlib
import sqlite3
import tempfile

HERE=pathlib.Path(__file__).resolve().parent
p=HERE/"news_rg_source_shadow_ingest_v1.py"
spec=importlib.util.spec_from_file_location("news_rg_ingest",str(p))
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def date(t):
    return dt.datetime.fromtimestamp(t,dt.timezone.utc).isoformat()

def main():
    now=1782570000
    stamp=date(now-120)
    def html(channel,base=5):
        pieces=[]
        for x in range(base,base+4):
            pieces.append(('<div data-post="'+channel+'/'+str(x)+'">'
             '<div class="tgme_widget_message_text" dir="auto">'
             'У каналі оприлюднили повідомлення про подію, яку перевіряють '
             'відповідальні органи та представники служб. Подробиці уточнюють.'
             '</div><a class="tgme_widget_message_photo_wrap" '
             'style="background-image:url(&quot;https://cdn.example.org/pic.jpg&quot;)"></a>'
             '<time datetime="'+stamp+'"></time></div>'))
        return "".join(pieces)
    def first(c,b):return html(c,5)
    def later(c,b):return html(c,5)
    with tempfile.TemporaryDirectory() as td:
        db=pathlib.Path(td)/"private_shadow.sqlite3"
        initial=m.scan_once(db,now,m.SOURCE_CHANNELS,first)
        assert initial["initialized_sources"]==19,initial
        assert initial["shadow_pending_rewrites"]==0
        fresh=m.scan_once(db,now+1,m.SOURCE_CHANNELS,later,bootstrap_recent=True)
        assert fresh["fresh_bootstrap_mode"] is True
        assert fresh["bootstrap_staged"]==24,fresh
        assert fresh["telegram_bot_api_calls"]==0 and fresh["publications"]==0
        cx=sqlite3.connect(str(db))
        count=cx.execute("SELECT COUNT(*) FROM story_shadow").fetchone()[0]
        assert count==24,count
        counts=dict(cx.execute(
            "SELECT channel,COUNT(*) FROM story_shadow GROUP BY channel"))
        assert len(counts)==19,counts
        assert set(counts)==set(m.SOURCE_CHANNELS)
        assert all(counts[x]==2 for x in m.BOOTSTRAP_EXTRA_PRIORITY),counts
        assert all(counts[x]==1 for x in m.SOURCE_CHANNELS
                   if x not in m.BOOTSTRAP_EXTRA_PRIORITY),counts
        assert cx.execute("SELECT COUNT(*) FROM editorial_draft").fetchone()[0]==0
        cx.close()
        duplicate=m.scan_once(db,now+2,m.SOURCE_CHANNELS,later,
                              bootstrap_recent=True)
        assert duplicate["bootstrap_staged"]==0,duplicate
        assert duplicate["shadow_pending_rewrites"]==24
        # Regular unattended scan must not backfill already observed numbers.
        normal=m.scan_once(db,now+3,m.SOURCE_CHANNELS,later)
        assert normal["new_stories_staged_for_editorial"]==0
        too_old=m.scan_once(db,now+2+m.FOUR_HOURS+60,
                            m.SOURCE_CHANNELS,later,bootstrap_recent=True)
        assert too_old["bootstrap_staged"]==0
        def malicious(c,b):
            return ('<div data-post="'+c+'/88"><div class="tgme_widget_message_text">'
               "Реклама: промокод, ставки на спорт. Це довгий тестовий текст."
               '</div><a class="tgme_widget_message_photo_wrap" '
               'style="background-image:url(&quot;https://cdn.example.org/pic.jpg&quot;)"></a>'
               '<time datetime="'+stamp+'"></time></div>')
        ad=m.scan_once(db,now+4,("Ateobreaking",),malicious,bootstrap_recent=True)
        assert ad["bootstrap_staged"]==0
    print("NEWS_RG_SHADOW_SOURCE_EXTENDED_REGRESSIONS_PASS")

if __name__=="__main__":
    main()
