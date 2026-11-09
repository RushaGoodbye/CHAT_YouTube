"""Stage RG V4 general no-face time-scene route, no active Studio changes."""
from pathlib import Path
import ast,json,hashlib,shutil
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
VERSION="RG_REPAIR_20261109_V4_NO_FACE_SCENE"
FILES=("rg_multi_dialogue.py","rg_face_anchor_guard_v1.py")

def replace_once(src,old,new,label):
    n=src.count(old)
    if n!=1:raise RuntimeError("ANCHOR_MISMATCH:"+label+":"+str(n))
    return src.replace(old,new,1)

def patch_multi(src):
    src=replace_once(src,
        "        valid_shots=[]\n        try:",
        "        valid_shots=[]\n        scene_time_candidates=[]\n        try:",
        "PREFLIGHT_INIT")
    src=replace_once(src,
        """                info=validate_dialogue_screenshot(sp,preflight_landmarker)
                if info.get('accepted'):
                    valid_shots.append(sp)""",
        """                info=validate_dialogue_screenshot(sp,preflight_landmarker)
                if not info.get('accepted'):
                    # No face is not proof of no dialogue. Preserve this shot
                    # ONLY if its timestamp and variable scene are usable.
                    # Independent scene match is still mandatory downstream.
                    from rg_face_anchor_guard_v1 import eligible_preflight
                    if eligible_preflight(info,sp):
                        info=dict(info)
                        info['accepted']=True
                        info['reason']='NO_FACE_SCENE_TIME_PENDING'
                        scene_time_candidates.append(Path(sp).name)
                if info.get('accepted'):
                    valid_shots.append(sp)""",
        "PREFLIGHT_VALIDATOR")
    src=replace_once(src,
        """            'skipped':skipped_screenshots,
        })""",
        """            'skipped':skipped_screenshots,
            'scene_time_candidates':scene_time_candidates,
            'scene_time_candidates_are_not_qa_pass':True,
        })""",
        "PREFLIGHT_REPORT")
    ast.parse(src)
    return src

def patch_face(src,helper):
    helper=helper.split('from __future__ import annotations',1)[1]
    helper=helper.replace('VERSION="RG_SCENE_TIME_NO_FACE_V4"',
                          'SCENE_TIME_VERSION="RG_SCENE_TIME_NO_FACE_V4"')
    helper=helper.replace('"policy":VERSION','"policy":SCENE_TIME_VERSION')
    src=replace_once(src,
        "def verify_and_rescue(video_path,resolved,video_duration,*,lookback_sec=1650.,lookahead_sec=150.):",
        helper+"\n\ndef verify_and_rescue(video_path,resolved,video_duration,*,lookback_sec=1650.,lookahead_sec=150.):",
        "SCENE_FUNCTION_INJECT")
    src=replace_once(src,
        """        if ref is None:
            raise RuntimeError(f"{rec['path'].name}: FACE_ANCHOR_REFERENCE_UNAVAILABLE ({refmeta.get('reason')})")""",
        """        if ref is None:
            # No face reference: independently establish the whole scene
            # and time against neighboring video anchors. Never forge
            # identity, and keep downstream boundary QA fully enabled.
            proof=prove_scene(video_path,records,i,original,video_duration,previous_confirmed)
            new=dict(rec)
            new['confirmation_meta']=proof
            new['source_name']='sequential_visual_order'
            updated.append(new)
            previous_confirmed=original
            print("RGSCENEV4|"+rec['path'].name+"|"+
                  str(proof.get('frame_time_sec'))+"|"+
                  str(proof.get('scene_score'))+"|"+
                  str(proof.get('contrast')),flush=True)
            continue""",
        "FACE_NONE_SAFE_SCENE")
    ast.parse(src)
    return src

def build(destination):
    dst=Path(destination)
    c=dst/"candidate";c.mkdir(parents=True,exist_ok=True)
    helper=(Path(__file__).parent/"rg_scene_time_guard_v4.py").read_text(encoding="utf-8")
    patches={
        "rg_multi_dialogue.py":lambda s:patch_multi(s),
        "rg_face_anchor_guard_v1.py":lambda s:patch_face(s,helper),
    }
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    files={}
    for name in FILES:
        src=APP/name;out=c/name
        out.write_text(patches[name](src.read_text(encoding="utf-8")),encoding="utf-8")
        files[name]={"source_sha256":digest(src),"candidate_sha256":digest(out)}
    manifest={"version":VERSION,"stage":"NOT_INSTALLED","files":files,
              "eligible_not_equivalent_to_qa_pass":True,
              "face_reference_proof_not_forged":True,"boundary_qa_required":True,
              "manual_review_when_scene_ambiguous":True,
              "automatic_reprocessing":False}
    (c/"RG_REPAIR_REPORT.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    source=Path(__file__).parent
    for name in ("install_v4.py","INSTALL_SCENE_V4.cmd","ROLLBACK_SCENE_V4.cmd","README_SCENE_V4.txt"):
        shutil.copy2(source/name,dst/name)
    print("RGV4|STAGED|"+str(dst))
    for name,meta in files.items():
        print("RGV4|CANDIDATE|"+name+"|"+meta["source_sha256"]+"|"+meta["candidate_sha256"])
if __name__=="__main__":
    import sys
    build(sys.argv[1])
