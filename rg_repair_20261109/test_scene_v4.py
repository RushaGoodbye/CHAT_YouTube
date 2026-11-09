"""RG no-face timestamp scene gate: real media read-only + negative controls."""
from pathlib import Path
import json,shutil,tempfile,sys
from unittest.mock import patch
import cv2,numpy as np

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
sys.path.insert(0,str(APP))
from stage_scene_v4 import patch_multi,patch_face
from rg_scene_time_guard_v4 import eligible_preflight,prove_scene

def main():
    # Ensure all patch anchors match currently installed production sources.
    a=patch_multi((APP/"rg_multi_dialogue.py").read_text(encoding="utf-8"))
    b=patch_face((APP/"rg_face_anchor_guard_v1.py").read_text(encoding="utf-8"),
                 (Path(__file__).parent/"rg_scene_time_guard_v4.py").read_text(encoding="utf-8"))
    assert "NO_FACE_SCENE_TIME_PENDING" in a
    assert "SCENE_TIME_NEIGHBORS_UNAVAILABLE" in b
    print("RGV4TEST|SOURCE_PATCH_AST|PASS",flush=True)
    source=json.loads((APP/"RG_EDITED_904_MULTI_DIALOGUE.json").read_text(encoding="utf-8-sig"))
    vr=Path(source["launch_args"]["video_root"])/"904.mp4"
    shot=Path(source["launch_args"]["screen_root"])/"904-3.jpg"
    assert vr.is_file() and shot.is_file()
    with tempfile.TemporaryDirectory(prefix="rg_v4_ascii_media_") as d:
        temp=Path(d)/"904-3.jpg"
        shutil.copy2(shot,temp)
        img=cv2.imread(str(temp))
        assert img is not None
        info={"accepted":False,"reason":"NO_GUEST_IN_RIGHT_WINDOW"}
        assert eligible_preflight(info,temp)
        assert not eligible_preflight({"accepted":False,"reason":"INVALID_IMAGE"},temp)
        print("RGV4TEST|NO_FACE_SCREENSHOT_ELIGIBLE|PASS",flush=True)
        recs=[
            {"path":Path("904-2.jpg"),"clock":{"seconds_of_day":79260},
             "winner":{"time":3507.0}},
            {"path":temp,"shot":img,"clock":{"seconds_of_day":79620},
             "winner":{"time":3978.5}},
            {"path":Path("904-4.jpg"),"clock":{"seconds_of_day":80580},
             "winner":{"time":4853.0}},
        ]
        from rg_clock_selector import _probe_duration
        result=prove_scene(vr,recs,1,3978.5,_probe_duration(vr),3507.0)
        print("RGV4TEST|REAL_904_3_SCENE|"+json.dumps(result,ensure_ascii=False),flush=True)
        assert result["accepted"]
        assert result["face_identity_proven"] is False
        assert result["boundary_verification_still_required"]
        bad=[dict(x) for x in recs]
        bad[2]=dict(bad[2],clock={"seconds_of_day":84000})
        try:
            prove_scene(vr,bad,1,3978.5,_probe_duration(vr),3507.0)
        except RuntimeError as exc:
            assert "CLOCK_NEIGHBOR_DISAGREEMENT" in str(exc),str(exc)
            print("RGV4TEST|BAD_CLOCK_FAIL_CLOSED|PASS",flush=True)
        else:
            raise AssertionError("BAD_CLOCK_NOT_BLOCKED")
    print("RGV4TEST|ACTIVE_SOURCE_AND_XML_UNCHANGED|TRUE",flush=True)
if __name__=="__main__":main()
