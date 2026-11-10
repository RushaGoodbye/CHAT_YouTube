"""Stage exact editor-confirmed popup overlays for 885 only.
Never touch worker, source MP4, original approved rendered MP4, or active queue.
Saved plan.json uses existing manual popup support; framed_host is preserved
as framed_host and requires a pending code patch before rerender.
"""
from pathlib import Path
import json,hashlib,os,uuid,time,sys
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
ROOT=DATA/"fullstream_v2"/"885"
INDEXES=(2,7,10,21,22,26,28,30,31,32)
def atomic(path, obj):
    tmp=path.with_name(path.name+"."+uuid.uuid4().hex[:6]+".tmp")
    try:
        tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)
def main():
    cached=(ROOT/"completed_popups_v76.json").read_bytes()
    scans=json.loads(cached.decode("utf-8-sig"))
    masks=scans["result"]["masks"]
    assert len(masks)==33
    rejected={int(x["index"]) for x in json.loads((ROOT/"V41_POPUP_VISUAL_REJECTIONS.json").read_text(encoding="utf-8-sig"))}
    if not set(INDEXES)<=rejected:raise RuntimeError("USER_LABEL_NOT_VISUALLY_REJECTED")
    plan_path=ROOT/"plan.json"
    sidecar=ROOT/"editor_confirmed_popup_885_v1.json"
    initial_plan=json.loads(plan_path.read_text(encoding="utf-8-sig")) if plan_path.exists() else {}
    if initial_plan.get("popup_masks"):raise RuntimeError("EXISTING_EDITOR_MASKS_REQUIRE_MANUAL_MERGE")
    current_plan=json.loads((ROOT/"processing_plan.json").read_text(encoding="utf-8-sig"))
    duration=float(current_plan["duration_seconds"])
    existing=current_plan["popup_masks"]
    selected=[]
    for idx in INDEXES:
        m=dict(masks[idx])
        x,y,w,h=map(int,(m[k] for k in ("x","y","width","height")))
        intervals=m["intervals"]
        assert x>=0 and y>=0 and x+w<=1920 and y+h<=1080
        assert len(intervals)==1 and 0<=intervals[0][0]<intervals[0][1]<=duration
        if idx==2:
            assert m["layout"]=="framed_host"
            assert 820<=x and 494<=y and x+w<=1400 and y+h<=815
        else:
            assert m["layout"]=="dual"
            assert 500<=x and 350<=y and x+w<=952 and y+h<=630
        m["layout_verified"]=True
        m["editor_confirmed"]=True
        m["candidate_index"]=idx
        m["evidence_type"]="USER_VERIFIED_CONTACT_SHEET_20261110"
        selected.append(m)
    for one in selected:
        if any(one["intervals"][0][0]<m["intervals"][-1][1] and m["intervals"][0][0]<one["intervals"][0][1] for m in existing):
            raise RuntimeError("MANUAL_MASK_OVERLAPS_EXISTING_NEEDS_MERGE")
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG_885_USER_CONFIRMED_10_POPUPS_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:5])
    backup.mkdir(parents=True,exist_ok=False)
    (backup/"completed_popups_v76_sha256.txt").write_text(hashlib.sha256(cached).hexdigest(),encoding="ascii")
    (backup/"processing_plan_before.json").write_bytes((ROOT/"processing_plan.json").read_bytes())
    (backup/"plan_exists.txt").write_text(str(plan_path.exists()),encoding="utf-8")
    if plan_path.exists():(backup/"plan_before.json").write_bytes(plan_path.read_bytes())
    if sidecar.exists():raise RuntimeError("SIDECAR_ALREADY_EXISTS_REVIEW")
    evidence={"schema":"RG_EDITOR_CONFIRMED_POPUP_MASKS_V1","stream":"885",
              "source_video":current_plan["video"],
              "source_duration":duration,
              "candidate_cache_sha256":hashlib.sha256(cached).hexdigest(),
              "confirmed_indexes":list(INDEXES),
              "editor_confirmed_count":len(selected),
              "unknown_candidate_indexes_remain_unverified":True,
              "popup_coverage_verified":False,"publish_ready":False,
              "existing_auto_masks":len(existing),
              "expected_total_render_masks":len(existing)+len(selected),
              "manual_masks":selected}
    changed=dict(initial_plan)
    changed["popup_masks"]=selected
    changed["editor_popup_evidence"]="editor_confirmed_popup_885_v1.json"
    try:
        atomic(sidecar,evidence)
        atomic(plan_path,changed)
        assert json.loads(sidecar.read_text(encoding="utf-8"))["confirmed_indexes"]==list(INDEXES)
        assert len(json.loads(plan_path.read_text(encoding="utf-8"))["popup_masks"])==10
        assert (ROOT/"processing_plan.json").read_bytes()==(backup/"processing_plan_before.json").read_bytes()
        print("RG885MASK|STAGED|10|FRAMED_HOST|1|DUAL|9",flush=True)
        print("RG885MASK|EXPECTED_TOTAL|18",flush=True)
        print("RG885MASK|PLAN|"+str(plan_path),flush=True)
        print("RG885MASK|EVIDENCE|"+str(sidecar),flush=True)
        print("RG885MASK|BACKUP|"+str(backup),flush=True)
        print("RG885MASK|APP_AND_MP4_UNTOUCHED|PASS",flush=True)
    except:
        sidecar.unlink(missing_ok=True)
        if (backup/"plan_before.json").exists():
            plan_path.write_bytes((backup/"plan_before.json").read_bytes())
        else:plan_path.unlink(missing_ok=True)
        print("RG885MASK|ROLLBACK|DONE",flush=True)
        raise
if __name__=="__main__":main()
