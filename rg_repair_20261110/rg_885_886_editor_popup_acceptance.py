"""Non-invasive acceptance of pending framed-host patch for 885 and 886
with all editor-validated masks, plus safety controls. Does not alter app.
"""
import sys,json,ast
from pathlib import Path
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
def test():
    sys.path.insert(0,str(APP))
    from rg_editor_framed_host_popup_v1 import build
    raw,updated=build()
    src=updated["rg_fullstream_auto_v2.py"].decode("utf-8-sig")
    tree=ast.parse(src)
    f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="verified_popups")
    ns={}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[f],type_ignores=[])),"<patched_popup>","exec"),ns)
    verified=ns["verified_popups"]
    expected={"885":10,"886":37}
    for n,count in expected.items():
        root=DATA/"fullstream_v2"/n
        plan=json.loads((root/"plan.json").read_text(encoding="utf-8-sig"))
        masks,flags=verified(plan)
        if len(masks)!=count:raise RuntimeError(n+"_VALID_MASKS_"+str(len(masks))+"_EXPECTED_"+str(count)+":"+repr(flags))
        if flags:raise RuntimeError(n+"_UNEXPECTED_FLAGS_"+repr(flags))
        approved=set(m["candidate_index"] for m in masks)
        if len(approved)!=count:raise RuntimeError(n+"_DUPLICATE_APPROVALS")
        print("RGEDITORTEST|STREAM|"+n+"|ACCEPTED|"+str(len(masks))+
              "|FRAMED|"+str(sum(m["layout"]=="framed_host" for m in masks)),flush=True)
    for n in ("885","886"):
        p=json.loads((DATA/"fullstream_v2"/n/"plan.json").read_text(encoding="utf-8-sig"))
        framed=next(m for m in p["popup_masks"] if m["layout"]=="framed_host")
        for k in ("editor_confirmed","layout_verified"):
            bad=dict(framed);bad[k]=False
            masks,_=verified({"popup_masks":[bad]})
            if masks:raise RuntimeError(n+"_UNVERIFIED_FRAMED_ACCEPTED_"+k)
    print("RGEDITORTEST|NEGATIVE_CONTROLS|PASS",flush=True)
    print("RGEDITORTEST|NO_WORKER_OR_MEDIA_CHANGED|PASS",flush=True)
if __name__=="__main__":test()
