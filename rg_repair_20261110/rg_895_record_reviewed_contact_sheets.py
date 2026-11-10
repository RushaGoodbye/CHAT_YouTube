"""Record source-bound visual review of user-shared RG895 contact sheets.
The assistant visually reviewed the images on 2026-11-10. The three
previously rejected visual candidates are NOT notification cards.
The 18 selected unknown-layout examples contain intro/outro, intermission
content, minute of silence, regular livestream scenes and no visible popups.
This is partial evidence only; NEVER claim full-stream verification.
Read plan and original evidence; do not change any render/queue/QA gate fields.
"""
from pathlib import Path
import json,os,uuid,time,hashlib
ROOT=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\fullstream_v2\895")
OUT=ROOT/"NOTIFICATION_QA_V93"
def read(p):
    return json.loads(p.read_text(encoding="utf-8-sig"))
def main():
    status=read(ROOT/"status.json")
    plan=read(ROOT/"processing_plan.json")
    raw=read(ROOT/"completed_popups_v76.json")["result"]
    rejected=read(ROOT/"V41_POPUP_VISUAL_REJECTIONS.json")
    manifest=read(OUT/"895_review_manifest.json")
    if status.get("state")!="PAUSED_EDITORIAL_QA" or plan.get("popup_coverage_verified") is not False:
        raise RuntimeError("QA_STATE_CHANGED_REFUSE")
    if len(plan.get("popup_masks",[]))!=20:raise RuntimeError("ACCEPTED_MASKS_CHANGED")
    indices=sorted(int(x["index"]) for x in rejected)
    if indices!=[12,18,19]:raise RuntimeError("REJECTED_CANDIDATES_CHANGED")
    if len(manifest["review_sheet_unknown_selected_times"])!=18:raise RuntimeError("UNKNOWN_SHEET_SAMPLES_CHANGED")
    if not (OUT/"895_three_rejected_candidates.jpg").is_file() or not (OUT/"895_unknown_layout_samples_part_01.jpg").is_file():
        raise RuntimeError("SOURCE_REVIEW_IMAGES_MISSING")
    decisions=[]
    notes={
        12:"Not notification: hand and decorative on-stream interface; red ROI on host frame",
        18:"Not notification: map interface content; red ROI covers part of map graphics",
        19:"Not notification: map and decorative interface elements"}
    for item in rejected:
        i=int(item["index"]);m=raw["masks"][i];intervals=m["intervals"][0]
        decisions.append({"candidate_index":i,"source_seconds":round(sum(map(float,intervals))/2,3),
          "classification":"NOT_A_NOTIFICATION","blur":False,
          "reviewer":"assistant_visual_inspection_of_user_uploaded_contact_sheet",
          "evidence_note":notes[i]})
    result={
        "schema":"RG895_CONTACT_SHEETS_VISUAL_VERDICT_V1","stream":"895",
        "source_manifest":str(OUT/"895_review_manifest.json"),
        "source_video":plan["video"],
        "source_duration_seconds":plan["duration_seconds"],
        "reviewed_contact_sheets":[
            {"file":str(OUT/"895_three_rejected_candidates.jpg"),
             "sha256":hashlib.sha256((OUT/"895_three_rejected_candidates.jpg").read_bytes()).hexdigest()},
            {"file":str(OUT/"895_unknown_layout_samples_part_01.jpg"),
             "sha256":hashlib.sha256((OUT/"895_unknown_layout_samples_part_01.jpg").read_bytes()).hexdigest()}],
        "rejected_candidate_decisions":decisions,
        "unknown_layout_contact_sheet_examples":{
            "sample_count":18,
            "source_seconds":manifest["review_sheet_unknown_selected_times"],
            "visible_notification_in_these_examples":False,
            "observations":"Stream intro, project graphics, live host/intermission, minute of silence, closing material",
            "minute_of_silence_do_not_modify":True,
            "NOT_source_wide_negative_proof":True},
        "existing_blur_masks_preserved":20,
        "unknown_layout_samples_from_original_scan":1263,
        "independent_10s_spot_scan_unknown_samples":64,
        "independent_10s_spot_scan_total_samples":1148,
        "full_notification_coverage_verified":False,
        "publish_ready":False,
        "qa_gate_bypass_allowed":False,
        "state":"EDITORIAL_REVIEW_PARTIAL_SOURCE_WIDE_COVERAGE_UNRESOLVED",
        "created_local_time":time.strftime("%Y-%m-%dT%H:%M:%S")
    }
    target=OUT/"895_visual_review_verdict_v1.json"
    if target.exists():
        prev=read(target)
        if prev.get("rejected_candidate_decisions") != decisions:
            raise RuntimeError("EXISTING_EDITORIAL_VERDICT_DIFFERS")
        print("RG895VERDICT|ALREADY_STAGED|PASS",flush=True)
    else:
        tmp=target.with_name(target.name+"."+uuid.uuid4().hex[:6]+".tmp")
        try:
            tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
            os.replace(tmp,target)
        finally:tmp.unlink(missing_ok=True)
    assert read(ROOT/"status.json")==status
    assert read(ROOT/"processing_plan.json")["popup_masks"]==plan["popup_masks"]
    print("RG895VERDICT|FALSE_VISUAL_CANDIDATES|12,18,19",flush=True)
    print("RG895VERDICT|UNKNOWN_SHEET_REVIEWED|18|NOTIFICATION_VISIBLE|0",flush=True)
    print("RG895VERDICT|SOURCE_WIDE_COVERAGE|UNVERIFIED",flush=True)
    print("RG895VERDICT|STAGED|"+str(target),flush=True)
    print("RG895VERDICT|PRODUCTION_PLAN_AND_QUEUE_UNTOUCHED|PASS",flush=True)
if __name__=="__main__":main()
