#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only R1 install runtime smoke test on authorized AlexPC.
No production runs, XML/media edits, nor launcher restarts.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
MARKER="# RG_SMOKING_UNCERTAIN_TIMELINE_HOTFIX_R1"
MODULE_HASHES={
    "rg_smoking_auto_export_v2.py":"b3b803151bcd37bedcb4e47c7e51710731676c1ea1ca22b9e1d086e4e913da1a",
    "rg_smoking_uncertainty_timeline_v1.py":"22654a4d764bd02f616dc7a0349c12e6e8463e925d00a4e35b6291a08aedb042",
}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    assert os.name == "nt","Windows self-hosted only"
    version=(APP/"rg_studio_version.py").read_text(encoding="utf-8-sig")
    assert 'STUDIO_VERSION="0.20.20.3"' in version,"Wrong Studio version"
    source=(APP/"rg_auto_edit_one_button.py").read_text(encoding="utf-8-sig")
    assert source.count(MARKER)==1,"Missing or duplicated R1 hotfix"
    assert source.count("# RG_SMOKING_TIMELINE_MARKERS_IMPORT_R1")==1
    assert "if not cigarette_detection.get('passed',False) and not _rg_cig_uncertain_review:" in source
    assert "out.stem != 'RG_EDITED_886_5'" in source
    for name,digest in MODULE_HASHES.items():
        assert sha(APP/name)==digest, f"Incorrect installed payload SHA: {name}"
    sys.path.insert(0,str(APP))
    bridge=importlib.import_module("rg_smoking_auto_export_v2")
    assert Path(bridge.__file__).resolve()==(APP/"rg_smoking_auto_export_v2.py").resolve()
    xml=('''<xmeml version="4"><sequence><name>892_1</name><duration>90</duration><rate>
<timebase>30</timebase><ntsc>FALSE</ntsc></rate>
<media><video><track>
<clipitem id="v1"><name>892.mp4</name><start>0</start><end>30</end><in>360</in><out>390</out></clipitem>
<clipitem id="v2"><name>892.mp4</name><start>30</start><end>90</end><in>400</in><out>460</out></clipitem>
</track></video><audio><track><clipitem id="a"><name>original.mp3</name></clipitem></track></audio>
</media></sequence></xmeml>''')
    report={'status':'AMBIGUOUS','raw_detection_count':1,
            'confirmed_track_count':0,'passed':False,
            'failures':['UNCONFIRMED_CIGARETTE_DETECTIONS'],
            'rejected_tracks':[{'hits':[{'t':12.25,'score':0.11,'class':'cigarette',
                                         'bbox':[100,100,120,120]}]}]}
    edited,side=bridge.prepare(xml,[report],"892_1","892")
    assert len(side["markers"])==1, side
    assert side["markers"][0]["start_frame"]==0, side
    assert side["markers"][0]["end_frame"]==26, side
    assert side.get("xml_was_source_overwritten") is False
    def tree(x):
        if "<!DOCTYPE xmeml>" in x:x=x.split("<!DOCTYPE xmeml>",1)[1].strip()
        return ET.fromstring(x)
    before,after=tree(xml),tree(edited)
    for path in ("./sequence/media/audio","./sequence/media/video"):
        assert ET.tostring(before.find(path))==ET.tostring(after.find(path))
    twice,twice_side=bridge.prepare(edited,[report],"892_1","892")
    assert len(twice_side["markers"])==1
    assert len(tree(twice).findall("./sequence/marker"))==1
    print("RG_SMOKING_R1_LIVE_MODULE_READONLY_SMOKE: PASS")
    print(json.dumps({"schema":"RG_SMOKING_R1_RUNTIME_PROOF_V1",
        "installed_studio_version":"0.20.20.3",
        "code_patch_present":True,
        "module_payload_sha_match":True,
        "runtime_import":True,
        "test_markers":len(side["markers"]),
        "test_marker_start_frame":side["markers"][0]["start_frame"],
        "test_marker_end_frame":side["markers"][0]["end_frame"],
        "audio_video_xml_subtrees_unchanged":True,
        "idempotent_markers":True,
        "8865_quarantine_code_guard_present":True,
        "production_media_modified":False,
        "real_dialogue_tested":False,
        "status":"INSTALL_RUNTIME_PROOF_PASS"},ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
