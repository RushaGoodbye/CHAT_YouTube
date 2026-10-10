#!/usr/bin/env python3
"""Automatic-only smoking compliance release decision.

Input from detector/segmenter and frame-by-frame QA, never user-painted masks.
A HOLD is machine-enforced output withholding, not a request for manual masking.
This module is a policy gate, not yet a complete smoking detector or renderer.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

Verdict = Literal["AUTO_PASS_BLURRED", "AUTO_PASS_CLEAN", "AUTO_HOLD"]

@dataclass(frozen=True)
class SceneEvidence:
    stream: str
    dialogue: str
    decoded_frames: int
    inspected_frames: int
    candidate_frames: int
    ambiguous_frames: int
    independently_validated_detector: bool = False
    independently_validated_smoke_model: bool = False
    dense_8865_negative_passed: bool = False
    detector_classifies_all_candidates: bool = False
    cigarette_identity_by_frame_verified: bool = False
    cigarette_mask_temporally_complete: bool = False
    finger_contact_coverage_verified: bool = False
    lip_contact_coverage_verified: bool = False
    smoke_coverage_verified: bool = False
    smoke_absence_or_presence_verified: bool = False
    blur_output_decoded_and_checked: bool = False
    video_timeline_full_coverage_verified: bool = False
    audio_passthrough_verified: bool = False
    original_media_unchanged: bool = False
    xml_atomic_publish_ready: bool = False
    release_metadata_provenance_verified: bool = False
    contains_manual_painted_masks: bool = False

def decide(e: SceneEvidence) -> dict:
    missing = []
    # A documented false positive in 886_5 cannot become auto-clear or be released
    # from an unrelated validation run.
    if e.dialogue == "886_5":
        missing.append("KNOWN_8865_FALSE_POSITIVE_QUARANTINE")

    if (e.decoded_frames < 1 or e.inspected_frames != e.decoded_frames
            or not e.video_timeline_full_coverage_verified):
        missing.append("FULL_FRAME_SCAN_NOT_VERIFIED")
    if e.contains_manual_painted_masks:
        missing.append("MANUAL_PAINTED_MASKS_NOT_AUTOMATIC")
    if not e.independently_validated_detector:
        missing.append("DETECTOR_NOT_VALIDATED_ON_POSITIVES_AND_NEGATIVES")
    if not e.dense_8865_negative_passed:
        missing.append("8865_DENSE_NEGATIVE_VALIDATION_PENDING")
    if not e.detector_classifies_all_candidates:
        missing.append("OBJECT_IDENTITY_UNRESOLVED")
    if e.ambiguous_frames > 0:
        missing.append("AMBIGUOUS_FRAMES_UNRESOLVED")
    if not e.smoke_absence_or_presence_verified:
        missing.append("SMOKE_STATE_NOT_VERIFIED")
    if not e.independently_validated_smoke_model:
        missing.append("SMOKE_MODEL_NOT_VALIDATED")

    if e.candidate_frames > 0:
        for good, reason in (
            (e.cigarette_identity_by_frame_verified, "CIGARETTE_IDENTITY_UNVERIFIED"),
            (e.cigarette_mask_temporally_complete, "CIGARETTE_TRACK_MASK_GAPS"),
            (e.finger_contact_coverage_verified, "FINGER_MASK_GAPS"),
            (e.lip_contact_coverage_verified, "MOUTH_MASK_GAPS"),
            (e.smoke_coverage_verified, "SMOKE_MASK_GAPS"),
            (e.blur_output_decoded_and_checked, "POST_BLUR_VISUAL_QA_INCOMPLETE"),
        ):
            if not good:
                missing.append(reason)

    for good, reason in (
        (e.audio_passthrough_verified, "AUDIO_NOT_VERIFIED_BIT_IDENTICAL"),
        (e.original_media_unchanged, "SOURCE_MEDIA_INTEGRITY_UNVERIFIED"),
        (e.xml_atomic_publish_ready, "ATOMIC_XML_DELIVERY_UNVERIFIED"),
        (e.release_metadata_provenance_verified, "PROVENANCE_UNVERIFIED"),
    ):
        if not good:
            missing.append(reason)

    if missing:
        return {
            "verdict": "AUTO_HOLD",
            "manual_editor_required": False,
            "automatic_publish_allowed": False,
            "withhold_xml": True,
            "reason_codes": missing,
        }
    return {
        "verdict": "AUTO_PASS_BLURRED" if e.candidate_frames else "AUTO_PASS_CLEAN",
        "manual_editor_required": False,
        "automatic_publish_allowed": True,
        "withhold_xml": False,
        "reason_codes": [],
    }

def selftest():
    def full(**kwargs):
        from dataclasses import replace
        x=SceneEvidence(stream="892",dialogue="892_1",decoded_frames=60,
                        inspected_frames=60,candidate_frames=60,ambiguous_frames=0,
                        independently_validated_detector=True,
                        independently_validated_smoke_model=True,
                        dense_8865_negative_passed=True,
                        detector_classifies_all_candidates=True,
                        cigarette_identity_by_frame_verified=True,
                        cigarette_mask_temporally_complete=True,
                        finger_contact_coverage_verified=True,
                        lip_contact_coverage_verified=True,
                        smoke_coverage_verified=True,
                        smoke_absence_or_presence_verified=True,
                        blur_output_decoded_and_checked=True,
                        video_timeline_full_coverage_verified=True,
                        audio_passthrough_verified=True,
                        original_media_unchanged=True,
                        xml_atomic_publish_ready=True,
                        release_metadata_provenance_verified=True)
        return replace(x,**kwargs)
    from dataclasses import replace
    assert decide(full())["verdict"]=="AUTO_PASS_BLURRED"
    assert decide(full(candidate_frames=0))["verdict"]=="AUTO_PASS_CLEAN"
    assert decide(full(independently_validated_smoke_model=False))["verdict"]=="AUTO_HOLD"
    assert decide(full(smoke_coverage_verified=False))["verdict"]=="AUTO_HOLD"
    assert decide(full(finger_contact_coverage_verified=False))["verdict"]=="AUTO_HOLD"
    assert decide(full(dialogue="886_5",candidate_frames=0))["verdict"]=="AUTO_HOLD"
    assert decide(full(contains_manual_painted_masks=True))["verdict"]=="AUTO_HOLD"
    assert decide(full(ambiguous_frames=2))["verdict"]=="AUTO_HOLD"
    assert decide(full(audio_passthrough_verified=False))["verdict"]=="AUTO_HOLD"
    assert decide(full(inspected_frames=59))["verdict"]=="AUTO_HOLD"
    assert decide(full(xml_atomic_publish_ready=False))["verdict"]=="AUTO_HOLD"
    assert all(decide(e)["manual_editor_required"] is False for e in
        [full(),full(ambiguous_frames=2),full(dialogue="886_5")])
    print("RG_AUTO_SMOKING_ONLY_RELEASE_POLICY_SELFTEST_PASS")

if __name__ == "__main__":
    selftest()
