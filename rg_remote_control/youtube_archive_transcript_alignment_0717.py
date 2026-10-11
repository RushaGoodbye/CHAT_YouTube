"""Read-only transcript/title alignment audit for an existing 0.7.17 SEO preview."""
import os,sys,sqlite3,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from rg_youtube_control.free_tools import fetch_transcript
ID="Ati19utM7Ck"
p=Path(os.environ["LOCALAPPDATA"])/"RGYouTubeControl"/"rg_youtube_control.db"
with sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True) as c:
    c.execute("PRAGMA query_only=ON")
    title=c.execute("SELECT title FROM videos WHERE video_id=?",(ID,)).fetchone()[0]
rows=fetch_transcript(ID)
terms={
    "fridge":["холодиль","холоділ","холодил","холодильник"],
    "relatives":["родич","родствен","рідн"],
    "petersburg":["питер","пітер","петербург","пітєр"],
    "war":["війна","война","войн","війни","войну"],
    "russian_march":["русский марш","руський марш","русского марша"],
    "constitution":["конституц"],
    "ukraine":["украин","україн"]
}
count={}
examples={}
for key,needles in terms.items():
    matched=[v for v in rows if any(word in str(v.get("text","")).casefold() for word in needles)]
    count[key]=len(matched)
    examples[key]=[{"at_s":round(float(x.get("start",0) or 0),1),"text":str(x.get("text",""))[:170]} for x in matched[:2]]
snap=[{"at_s":round(float(x.get("start",0) or 0),1),"text":str(x.get("text",""))[:160]} for x in rows[:5]]
print(json.dumps({"schema":"RG_ARCHIVE_TRANSCRIPT_ALIGN_READONLY_V1","video_id":ID,"current_title":title,"transcript_lines":len(rows),"term_counts":count,"examples":examples,"first_lines":snap,"youtube_api_quota":0,"video_changes":0,"db_writes":0},ensure_ascii=True,separators=(",",":")))
