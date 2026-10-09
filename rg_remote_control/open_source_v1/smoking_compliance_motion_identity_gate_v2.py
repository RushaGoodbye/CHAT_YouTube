#!/usr/bin/env python3
"""Fail-closed smoking compliance: motion != finger/mouth/smoke identity.

Offline stdlib QA; no editing video, no XML/audio writes or production release.
Tests explicitly regress real 892 mouth-overlap defect from 2026-10-09.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass

@dataclass(frozen=True)
class Observation:
    stream: str
    frame: int
    cigarette_semantically_verified: bool = False
    grip_is_real_fingers_verified: bool = False
    smoke_present: bool = False
    smoke_covered_verified: bool = False
    mouth_contact: bool = False
    mouth_landmarks_verified: bool = False
    mouth_covered_verified: bool = False
    mask_inside_local_roi: bool = False
    no_visible_cigarette_after_blur_verified: bool = False
    timeline_smoking_coverage_reviewed: bool = False
    no_false_positive_microphone_verified: bool = False

def gate(e: Observation):
    reasons = []
    if e.stream == "886":
        reasons.append("886_5_MICROPHONE_QUARANTINE_NO_PUBLISH")
    if not e.cigarette_semantically_verified:
        reasons.append("CIGARETTE_IDENTITY_UNVERIFIED")
    if not e.grip_is_real_fingers_verified:
        reasons.append("GRIP_GEOMETRY_IS_NOT_HAND_IDENTITY")
    if e.smoke_present and not e.smoke_covered_verified:
        reasons.append("SMOKE_MASK_UNVERIFIED")
    if e.mouth_contact and (not e.mouth_landmarks_verified or not e.mouth_covered_verified):
        reasons.append("MOUTH_KEYPOINTS_OR_COVERAGE_UNVERIFIED")
    if not e.mask_inside_local_roi:
        reasons.append("MASK_NOT_CONFIRMED_LOCAL")
    if not e.no_visible_cigarette_after_blur_verified:
        reasons.append("CIGARETTE_COULD_STILL_BE_VISIBLE")
    if not e.timeline_smoking_coverage_reviewed:
        reasons.append("FULL_SCENE_TIMELINE_NOT_REVIEWED")
    if not e.no_false_positive_microphone_verified:
        reasons.append("MICROPHONE_NEGATIVE_REVIEW_INCOMPLETE")
    # This is SHADOW readiness only. Never hands back a production approval.
    return {"status": "REVIEW_REQUIRED" if reasons else "SHADOW_QA_READY_NO_RELEASE",
            "reasons": reasons, "automatic_blur_allowed": False,
            "release_allowed": False, "Studio_modified": False,
            "source_audio_modified": False, "Premiere_XML_modified": False,
            "quarantine_886_5_unchanged": True}

def selftest():
    positive = Observation("892", 50, cigarette_semantically_verified=True,
                           mask_inside_local_roi=True)
    r = gate(positive)
    assert r["status"] == "REVIEW_REQUIRED"
    assert "GRIP_GEOMETRY_IS_NOT_HAND_IDENTITY" in r["reasons"]
    # Even if geometric ellipse moves 208 pixels and never loses optical flow,
    # hand identity cannot be inferred from that displacement.
    assert r["automatic_blur_allowed"] is False
    assert "MOUTH_KEYPOINTS_OR_COVERAGE_UNVERIFIED" in gate(
        Observation("892", 50, cigarette_semantically_verified=True,
                    grip_is_real_fingers_verified=True, mouth_contact=True))["reasons"]
    assert "SMOKE_MASK_UNVERIFIED" in gate(
        Observation("892", 20, cigarette_semantically_verified=True, smoke_present=True))["reasons"]
    # A microphone shaped like a cigarette must never be promoted to smoking.
    a=Observation("886", 10, cigarette_semantically_verified=True,
                  grip_is_real_fingers_verified=True,
                  smoke_present=False, mouth_contact=False,
                  mask_inside_local_roi=True,
                  no_visible_cigarette_after_blur_verified=True,
                  timeline_smoking_coverage_reviewed=True,
                  no_false_positive_microphone_verified=True)
    assert "886_5_MICROPHONE_QUARANTINE_NO_PUBLISH" in gate(a)["reasons"]
    fully_documented=Observation("892", 50, cigarette_semantically_verified=True,
        grip_is_real_fingers_verified=True, smoke_present=True, smoke_covered_verified=True,
        mouth_contact=True, mouth_landmarks_verified=True,mouth_covered_verified=True,
        mask_inside_local_roi=True, no_visible_cigarette_after_blur_verified=True,
        timeline_smoking_coverage_reviewed=True, no_false_positive_microphone_verified=True)
    r=gate(fully_documented)
    assert r["status"]=="SHADOW_QA_READY_NO_RELEASE"
    assert r["automatic_blur_allowed"] is False and r["release_allowed"] is False
    print("RG_SMOKING_MOTION_IDENTITY_GATE_V2_FINGER_VS_MOUTH_886_NEGATIVE: PASS")

if __name__=="__main__":selftest()
