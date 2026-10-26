#!/usr/bin/env python3
"""Locate stream 907 manifests and XML without modifying files."""
import json,os
from pathlib import Path
ROOTS=[Path(r"F:\RG_AUTO_EDIT"),Path(r"\\Desktop-v7gg0en\record")]
def main():
    rows=[]
    for root in ROOTS:
        if not root.exists():
            rows.append({"root":str(root),"status":"UNAVAILABLE"});continue
        n=0
        for base,dirs,files in os.walk(root):
            dirs[:]=[d for d in dirs if d.lower() not in {"venv",".git","node_modules","__pycache__","site-packages","models","cache","temp","tmp"}]
            for name in files:
                low=name.lower()
                if "907" not in low or not low.endswith((".json",".xml")):continue
                p=Path(base)/name
                n+=1
                if n>150:break
                try:
                    meta={"file":str(p),"size":p.stat().st_size}
                    if low.endswith(".json") and ("multi_dialogue" in low or "manifest" in low):
                        try:
                            doc=json.loads(p.read_text(encoding="utf-8-sig"))
                            meta.update({"stream":doc.get("stream"),"status":doc.get("status"),"dialogue_count":doc.get("dialogue_count"),"outputs":len(doc.get("outputs") or []),"review_holds":len(doc.get("review_holds") or [])})
                        except Exception as e:meta["parse_error"]=type(e).__name__
                    rows.append(meta)
                except OSError:pass
            if n>150:break
        rows.append({"root":str(root),"candidate_count":n})
    print("RG907|LOCATE_OUTPUTS|"+json.dumps({"read_only":True,"results":rows},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
