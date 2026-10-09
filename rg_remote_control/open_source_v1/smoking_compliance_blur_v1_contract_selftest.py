#!/usr/bin/env python3
"""No-dependency regression for RG four-layer smoking blur shadow requirements.

Spec acceptance tests only: never detects, blurs, renders, edits, or releases.
The human-annotated original scene and the 886_5 true negative must still be
independently tested before connecting to a real renderer.
"""
from __future__ import annotations
import json
from pathlib import Path

SPEC=Path(__file__).with_name("smoking_compliance_blur_v1_acceptance.json")
SCHEMA="RG_SMOKING_COMPLIANCE_BLUR_ACCEPTANCE_V1"
LAYERS=("cigarette","grip","smoke","mouth")

def mask_decision(state, observations, masks, human_negative_sha=None):
    if state=="VERIFIED_NEGATIVE":
        if not (isinstance(human_negative_sha,str) and len(human_negative_sha)==64):
            return "REVIEW_REQUIRED"
        return "FALSE_POSITIVE_REVIEW" if any(masks.values()) else "NO_BLUR_EXACT_VERIFIED_REFERENCE"
    if state!="CONFIRMED_SMOKING":
        return "REVIEW_REQUIRED"
    if set(masks)!=set(LAYERS):
        return "REVIEW_REQUIRED"
    required={"cigarette":observations.get("cigarette_visible",False),
              "grip":observations.get("held_in_hand",False),
              "smoke":observations.get("smoke_visible",False),
              "mouth":observations.get("mouth_contact",False)}
    if not any(required.values()):
        return "REVIEW_REQUIRED"
    if any(required[key] and not masks[key] for key in LAYERS):
        return "REVIEW_REQUIRED"
    if any(not required[key] and masks[key] for key in LAYERS):
        return "REVIEW_REQUIRED"
    return "SHADOW_QA_ONLY"   # NEVER release/Studio or media rewrite.

def test():
    c=json.loads(SPEC.read_text(encoding="utf-8"))
    assert c["schema"]==SCHEMA and c["contour"]=="auto_edit"
    assert tuple(c["classes"])==LAYERS and c["mask_operation"]=="UNION"
    assert c["processing_mode"]=="SMOKING_COMPLIANCE_BLUR"
    assert c["supersedes_target_mask_requirement"]=="CIGARETTE_ONLY_BLUR"
    assert c["positive_reference"]["stream"]=="892"
    assert c["negative_reference"]["dialogue"]=="886_5"
    assert c["negative_reference"]["quarantine"] is True
    assert c["negative_reference"]["full_negative_video_test_passed"] is False
    for key in ("automatic_blur_allowed","production_release_allowed",
                "Studio_modified","source_video_modified","original_audio_modified",
                "premiere_XML_modified","platform_moderation_guaranteed"):
        assert c[key] is False,(key,c[key])
    assert c["quarantine_886_5_unchanged"] is True
    for key,value in c["safety_guards"].items():
        assert value is True,key
    observations=dict(cigarette_visible=True,held_in_hand=True,smoke_visible=True,mouth_contact=True)
    masks={x:{i} for i,x in enumerate(LAYERS)}
    assert mask_decision("CONFIRMED_SMOKING",observations,masks)=="SHADOW_QA_ONLY"
    for key in LAYERS:
        broken={k:set(v) for k,v in masks.items()}
        broken[key]=set()
        assert mask_decision("CONFIRMED_SMOKING",observations,broken)=="REVIEW_REQUIRED",key
    assert mask_decision("SUSPECTED_SMOKING",observations,masks)=="REVIEW_REQUIRED"
    assert mask_decision("TRACK_LOST",observations,masks)=="REVIEW_REQUIRED"
    assert mask_decision("NO_SMOKING_DETECTED",observations,masks)=="REVIEW_REQUIRED"
    empty={x:set() for x in LAYERS}
    assert mask_decision("VERIFIED_NEGATIVE",{},empty)=="REVIEW_REQUIRED"
    assert mask_decision("VERIFIED_NEGATIVE",{},empty,"a"*64)=="NO_BLUR_EXACT_VERIFIED_REFERENCE"
    assert mask_decision("VERIFIED_NEGATIVE",{},masks,"a"*64)=="FALSE_POSITIVE_REVIEW"
    print("RG_SMOKING_COMPLIANCE_BLUR_V1_FOUR_ZONE_REQUIREMENT_AND_886_HARDNEG: PASS")

if __name__=="__main__":
    test()
