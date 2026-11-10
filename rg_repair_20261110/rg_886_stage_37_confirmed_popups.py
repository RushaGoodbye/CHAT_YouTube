"""Stage 37 user-confirmed 886 popup rectangles for next Studio QA-only review.
No running worker touched, no export, no changes to source or finished MP4.
"""
from pathlib import Path
import json, hashlib, os, uuid, time
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
ROOT=DATA/"fullstream_v2"/"886"
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
INDICES=(6,7,8,9,17,19,22,23,24,28,29,30,31,32,35,39,40,41,50,51,53,59,68,69,72,73,74,75,77,78,80,81,82,83,85,87,89)
def atomic(path, obj):
    tmp=path.with_name(path.name+"."+uuid.uuid4().hex[:8]+".tmp")
    try:
        tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)
def main():
    if len(set(INDICES))!=37:raise RuntimeError("DUPLICATE_USER_INDEX")
    raw=(ROOT/"completed_popups_v76.json").read_bytes()
    scans=json.loads(raw.decode("utf-8-sig"))
    all_masks=scans["result"]["masks"]
    rejections=json.loads((ROOT/"V41_POPUP_VISUAL_REJECTIONS.json").read_text(encoding="utf-8-sig"))
    rejected={int(z["index"]) for z in rejections}
    if len(all_masks)!=95 or len(rejections)!=66 or not set(INDICES)<=rejected:
        raise RuntimeError("INVALID_OR_CHANGED_SOURCE_CANDIDATE_SET")
    planpath=ROOT/"plan.json"
    sidecar=ROOT/"editor_confirmed_popup_886_v1.json"
    plan=json.loads((ROOT/"processing_plan.json").read_text(encoding="utf-8-sig"))
    old_plan=json.loads(planpath.read_text(encoding="utf-8-sig")) if planpath.is_file() else {}
    if old_plan.get("popup_masks"):
        raise RuntimeError("EDITOR_MASKS_ALREADY_PRESENT_NOT_OVERWRITING")
    if sidecar.exists():raise RuntimeError("EDITOR_CONFIRMATION_ALREADY_STAGED")
    duration=float(plan["duration_seconds"])
    old=plan["popup_masks"]
    if len(old)!=29:raise RuntimeError("EXISTING_AUTO_MASKS_CHANGED")
    approved=[]
    for i in INDICES:
        mask=dict(all_masks[i])
        x,y,w,h=map(int,(mask[k] for k in ("x","y","width","height")))
        if not (0<=x<x+w<=1920 and 0<=y<y+h<=1080):raise RuntimeError("BOX_OUT_OF_FRAME_"+str(i))
        if len(mask.get("intervals",[]))!=1:raise RuntimeError("MULTIPLE_INTERVALS_"+str(i))
        a,b=map(float,mask["intervals"][0])
        if not 0<=a<b<=duration:raise RuntimeError("TIME_RANGE_INVALID_"+str(i))
        layout=mask.get("layout")
        if layout=="framed_host":
            if not (820<=x and 494<=y and x+w<=1400 and y+h<=815):
                raise RuntimeError("FRAMED_HOST_OUT_OF_SAFE_BOUNDS_"+str(i))
        elif layout=="dual":
            if not (500<=x and 350<=y and x+w<=952 and y+h<=630):
                raise RuntimeError("DUAL_OUT_OF_SAFE_BOUNDS_"+str(i))
        else:raise RuntimeError("UNSUPPORTED_LAYOUT_"+str(i)+"_"+str(layout))
        mask.update(editor_confirmed=True,layout_verified=True,candidate_index=i,
                    evidence_type="USER_VERIFIED_CONTACT_SHEETS_20261110")
        approved.append(mask)
    duplicates=[]
    for mask in approved:
        for m in old:
            a,b=mask["intervals"][0];c,d=m["intervals"][0]
            if a<d and c<b:
                duplicates.append((mask["candidate_index"],m.get("layout"),[c,d]))
    if duplicates:raise RuntimeError("EXISTING_MASK_INTERVAL_COLLISION:"+repr(duplicates))
    counts={}
    for mask in approved:counts[mask["layout"]]=counts.get(mask["layout"],0)+1
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG_886_USER_CONFIRMED_37_POPUPS_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:5])
    backup.mkdir(parents=True,exist_ok=False)
    if planpath.exists():(backup/"plan_before.json").write_bytes(planpath.read_bytes())
    (backup/"processing_plan_before.json").write_bytes((ROOT/"processing_plan.json").read_bytes())
    (backup/"886_status_before.json").write_bytes((ROOT/"status.json").read_bytes())
    evidence={"schema":"RG_EDITOR_CONFIRMED_POPUP_MASKS_V1","stream":"886",
              "source_video":plan["video"],"source_duration_seconds":duration,
              "candidate_cache_sha256":hashlib.sha256(raw).hexdigest(),
              "confirmed_candidate_indexes":list(INDICES),
              "editor_confirmed_count":37,"by_layout":counts,
              "popup_coverage_verified":False,"publish_ready":False,
              "other_rejected_candidates_still_unverified":True,
              "existing_auto_masks":len(old),
              "expected_total_render_masks":len(old)+37,
              "manual_masks":approved}
    amended=dict(old_plan)
    amended["popup_masks"]=approved
    amended["editor_popup_evidence"]="editor_confirmed_popup_886_v1.json"
    try:
        atomic(sidecar,evidence)
        atomic(planpath,amended)
        assert len(json.loads(planpath.read_text(encoding="utf-8"))["popup_masks"])==37
        assert (ROOT/"processing_plan.json").read_bytes()==(backup/"processing_plan_before.json").read_bytes()
        assert (ROOT/"status.json").read_bytes()==(backup/"886_status_before.json").read_bytes()
        print("RG886EDIT|STAGED|37|LAYOUTS|"+json.dumps(counts),flush=True)
        print("RG886EDIT|TOTAL_EXPECTED|66",flush=True)
        print("RG886EDIT|EVIDENCE|"+str(sidecar),flush=True)
        print("RG886EDIT|BACKUP|"+str(backup),flush=True)
        print("RG886EDIT|QA_COVERAGE_UNVERIFIED|TRUE",flush=True)
        print("RG886EDIT|WORKER_QUEUE_MP4_UNTOUCHED|PASS",flush=True)
    except:
        sidecar.unlink(missing_ok=True)
        previous=backup/"plan_before.json"
        if previous.is_file():planpath.write_bytes(previous.read_bytes())
        else:planpath.unlink(missing_ok=True)
        print("RG886EDIT|ROLLED_BACK",flush=True)
        raise
if __name__=="__main__":main()
