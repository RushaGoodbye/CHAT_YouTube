"""Stage strict isolated Release Health fix.

No production writes. The current-run manifest is required to recognize a
revision-only single dialogue and to document an absent screenshot index.
"""
from __future__ import annotations
import ast
from pathlib import Path

def once(text,old,new):
    if text.count(old)!=1:raise RuntimeError(f"ANCHOR_MISMATCH_{text.count(old)}:{old[:65]}")
    return text.replace(old,new,1)

def patch_source(s):
    old='''    if total==1 and stem.casefold()==f"RG_EDITED_{stream}".casefold():
        return 1
    return None'''
    new='''    if total==1 and stem.casefold()==f"RG_EDITED_{stream}".casefold():
        return 1
    # A single R2 file is revision 2 of dialogue 1, not dialogue 2.
    # Accept only when the current manifest proves the exact file and
    # screenshot index. Never infer identity from revision alone.
    rev=re.fullmatch(r"RG_EDITED_"+re.escape(str(stream))+r"_R[1-9]\\\d*",stem,re.I)
    if total==1 and rev:
        x=Path(path)
        manifest=x.parent.parent/("RG_EDITED_"+str(stream)+"_MULTI_DIALOGUE.json")
        try:
            data=json.loads(manifest.read_text(encoding="utf-8-sig"))
            rows=data.get("outputs") or []
            if (str(data.get("stream"))==str(stream)
                    and str(data.get("status")) in ("QA_FAILED","DIALOGUES_COMPLETE")
                    and int(data.get("dialogue_count") or 0)==1
                    and len(rows)==1
                    and int(rows[0].get("index") or 0)==1
                    and x.name.casefold()==Path(str(rows[0].get("premiere_xml") or "")).name.casefold()
                    and re.fullmatch(re.escape(str(stream))+r"-\\\d+\\\.(?:jpg|jpeg|png)",
                                     Path(str(rows[0].get("screenshot") or "")).name,re.I)):
                return 1
        except (OSError,ValueError,TypeError,KeyError):pass
    return None'''
    s=once(s,old,new)
    # Intentionally do NOT suppress nonconsecutive dialogue detection.
    # 904-3 screenshot is excluded by preflight, but still needs human confirmation.
    ast.parse(s)
    return s

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--source",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    source=Path(a.source);dest=Path(a.out)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(patch_source(source.read_text(encoding="utf-8")),encoding="utf-8")
    print("RG_RELEASE_HEALTH_PATCH|STAGED|"+str(dest))
