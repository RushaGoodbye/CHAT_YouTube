#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only installed Audalign epoch R1 proof for failed dialogue 904_5.
Never edits source audio/video, Studio configuration, XML or checkpoints.
"""
from __future__ import annotations
import ast
import hashlib
import json
import os
from pathlib import Path
import sys

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
EXPECTED_HELPER_SHA256="62b54412fb2a95ae0c15bd798930b8688dbb38476403fabfb58fd1b22987f6a8"
TAG="# RG_AUDALIGN_DIALOGUE_EPOCH_HOTFIX_R1"

def main():
    assert os.name=="nt","Windows runner required"
    app=APP
    source=(app/"rg_auto_edit_one_button.py")
    guard=app/"rg_audalign_epoch_guard_v1.py"
    manifest=app/"RG_EDITED_904_MULTI_DIALOGUE.json"
    audit=app/"RG_EDITED_904_5_audio_source_audit.json"
    assert all(p.is_file() for p in (source,guard,manifest,audit)),"Missing actual Studio component"
    data=source.read_text(encoding="utf-8-sig")
    assert data.count(TAG)==1,"Missing or duplicate epoch injection"
    assert "sync, _rg_epoch_review = _rg_choose_sync_epoch(sync, dialogue_ranges[0])" in data,"Patch hook missing"
    assert "sync=refine_dialogue_sync(" in data,"Local Audalign validation must remain present"
    ast.parse(data,filename=source.name)
    assert hashlib.sha256(guard.read_bytes()).hexdigest()==EXPECTED_HELPER_SHA256, "Helper SHA differs from distributed package"
    assert 'STUDIO_VERSION="0.20.20.3"' in (app/"rg_studio_version.py").read_text(encoding="utf-8-sig")
    job=json.loads(manifest.read_text(encoding="utf-8-sig"))
    assert job["stream"]=="904" and job["status"]=="FAILED"
    assert job["failed_dialogue"]==4 and len(job["outputs"])==3
    for row in job["outputs"]:
        assert Path(row["xml"]).is_file(), "Prior checkpoint missing"
    sys.path.insert(0,str(app))
    from rg_audalign_epoch_guard_v1 import choose_for_dialogue
    info=json.loads(audit.read_text(encoding="utf-8-sig"))
    sync={"offset_sec":info["sync_offset_sec"],"speed_ratio":info["sync_speed_ratio"],
          "confidence":info["sync_confidence"],
          "robust_inliers":info["robust_inliers"],"robust_rejected_points":info["robust_rejected_points"],
          "piecewise_audio_sync":info["piecewise_audio_sync"]}
    d=info["dialogue_anchor"]
    proposed,review=choose_for_dialogue(sync,{"start":d["dialogue_start_sec"],"end":d["dialogue_end_sec"]})
    assert review["state"]=="PROPOSED_LOCAL_EPOCH",review
    assert 292.8<float(proposed["offset_sec"])<293.2
    assert proposed["confidence"]=="low","Must not bypass downstream local Audalign check"
    assert proposed["piecewise_audio_sync"]["enabled"] is False
    report={
        "schema":"RG_904_EPOCH_R1_INSTALLED_RUNTIME_PROOF_V1",
        "installed":True,
        "studio_version":"0.20.20.3",
        "patch_singleton":True,
        "helper_sha256_matched":True,
        "real_904_5_epoch_state":review["state"],
        "real_904_5_proposed_offset_sec":proposed["offset_sec"],
        "local_correlation_still_required":True,
        "completed_xmls_preserved":[Path(x["xml"]).name for x in job["outputs"]],
        "resume_from_failed_job":job["failed_dialogue"],
        "stream_processing_restarted":False,
        "production_writes":False,
        "status":"PASS"
    }
    print("RG_904_EPOCH_R1_INSTALLED_RUNTIME_PROOF_PASS")
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
