#!/usr/bin/env python3
"""NEWS RG quota compliance and idempotence against temporary SQLite only."""
import importlib.util
import pathlib
import sqlite3
import tempfile
import time

here=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "news_rg_ai",str(here/"news_rg_editorial_rewrite_shadow_v1.py"))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def main():
    pol=m.policy()
    original=("У місті місцева влада повідомила про подію. "
              "Офіційні служби перевіряють ситуацію та повідомляють "
              "про уточнення обставин. ")*10
    body=("Відповідальні служби повідомили про інцидент, "
          "обставини якого зараз уточнюються. Інші деталі "
          "потребують незалежного підтвердження. ")*7
    body=body[:750].rstrip(". ,")+"."
    draft={"relevant":True,"is_ad":False,
           "headline":"У місті перевіряють обставини інциденту",
           "body":body}
    assert m.validate_candidate(draft,original,"https://cdn.example.org/photo.jpg",pol) is None
    with tempfile.TemporaryDirectory() as td:
        db=pathlib.Path(td)/"staged.sqlite3"
        cx=sqlite3.connect(str(db))
        cx.executescript("""CREATE TABLE story_shadow(
            key TEXT PRIMARY KEY,channel TEXT,text TEXT,posted_at INT,
            media_url TEXT,media_type TEXT,status TEXT);
            CREATE TABLE editorial_draft(
            key TEXT PRIMARY KEY,headline TEXT,body TEXT,validated_at INT);""")
        for i in range(1,17):
            cx.execute("INSERT INTO story_shadow VALUES(?,?,?,?,?,?,?)",(
                "story_"+str(i),"Ateobreaking",original,int(time.time())-100+i,
                "https://cdn.example.org/photo.jpg","photo",
                "needs_editorial_rewrite"))
        cx.commit();cx.close()
        requests=[]
        def fake(prompt):
            requests.append(prompt)
            return draft
        outcomes=[]
        for _ in range(5):
            outcomes.append(m.run(db,provider=fake,allowed=True))
        assert len(requests)==10, len(requests)
        cx=sqlite3.connect(str(db))
        assert cx.execute("SELECT COUNT(*) FROM editorial_ai_budget").fetchone()[0]==10
        assert cx.execute("SELECT COUNT(*) FROM editorial_draft").fetchone()[0]==10
        assert cx.execute("SELECT COUNT(*) FROM story_shadow WHERE status='needs_editorial_rewrite'").fetchone()[0]==6
        cx.close()
        assert outcomes[-1]["ai_budget_guard_blocked"] is True
        # A rejected draft also reserves its one AI unit; no repeated billing.
        blocked=m.run(db,provider=fake,allowed=True)
        assert len(requests)==10 and blocked["ai_requests"]==0
        assert blocked["publications"]==0 and blocked["telegram_calls"]==0
    print("NEWS_RG_AI_TEN_PER_ROLLING_DAY_QUOTA_SELFTEST_PASS")

if __name__=="__main__":main()
