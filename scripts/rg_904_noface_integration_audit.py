"""Strict, read-only 904 no-face integration gate.

Staging is in GitHub runner temp; never install, edit XML or touch queue.
"""
from pathlib import Path
import json, sys, ast, tempfile, hashlib
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
sys.path.insert(0,str(APP))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"rg_repair_20261109"))
from stage_scene_v4 import patch_multi, patch_face
def main():
    manifest=json.loads((APP/"RG_EDITED_904_MULTI_DIALOGUE.json").read_text(encoding="utf-8-sig"))
    helper=(Path(__file__).resolve().parents[1]/"rg_repair_20261109"/"rg_scene_time_guard_v4.py").read_text(encoding="utf-8")
    for name,patch in (
        ("rg_multi_dialogue.py",lambda s:patch_multi(s)),
        ("rg_face_anchor_guard_v1.py",lambda s:patch_face(s,helper)),
    ):
        path=APP/name
        source=path.read_text(encoding="utf-8")
        original_hash=hashlib.sha256(path.read_bytes()).hexdigest()
        candidate=patch(source)
        ast.parse(candidate)
        assert hashlib.sha256(path.read_bytes()).hexdigest()==original_hash
        print("RG904INTEGRATION|STAGED_PATCH|"+name+"|AST_PASS|SOURCE_UNMODIFIED",flush=True)
    outputs={int(o["screenshot"].split("-")[1].split(".")[0]):o for o in manifest["outputs"]}
    assert 3 not in outputs, "THIRD_IS_ALREADY_IN_PRODUCTION_RECHECK"
    assert 2 in outputs and 4 in outputs
    candidate=(3962.9,4387.6)
    print("RG904INTEGRATION|904-3_SHADOW_BOUNDARY|"+str(candidate[0])+"|"+str(candidate[1]),flush=True)
    overlaps=[]
    for n in (2,4):
        item=outputs[n]
        lo=float(item["range"]["start"]); hi=float(item["range"]["end"])
        overlap=max(0.,min(hi,candidate[1])-max(lo,candidate[0]))
        print("RG904INTEGRATION|NEIGHBOR|"+str(n)+"|"+str(lo)+"|"+str(hi)+"|OVERLAP_SEC="+str(round(overlap,2)),flush=True)
        if overlap>2:overlaps.append({"screenshot":n,"overlap_seconds":round(overlap,2)})
    outcome={
        "stream":904,"status":"QA_BLOCKED_OVERLAPPING_BOUNDARIES" if overlaps else "CANDIDATE_ONLY",
        "production_modified":False,"candidate_904_3":{"start":candidate[0],"end":candidate[1]},
        "overlaps":overlaps,"release_approved":False,
        "next_step":"independent speaker/scene-based re-boundary on all three clips before XML generation",
    }
    print("RG904INTEGRATION|FINAL|"+json.dumps(outcome,ensure_ascii=False),flush=True)
    report=Path(sys.argv[1]);report.write_text(json.dumps(outcome,ensure_ascii=False,indent=2),encoding="utf-8")
if __name__=="__main__":main()
