"""Read-only decision policy for no-guest screenshot fallback.

Does not create dialogues or approve exports; a visual candidate always needs
boundary and overlap QA before production use.
"""
from dataclasses import dataclass
from math import isfinite

@dataclass(frozen=True)
class SceneEvidence:
    clock_sec: float
    matched_sec: float
    score: float
    peak_over_p75: float
    screenshot_decoded: bool
    has_right_guest: bool
    frame_consistency: bool

def assess_no_face_scene(e: SceneEvidence) -> tuple[bool, str]:
    if e.has_right_guest:
        return False, "NOT_A_NO_FACE_CASE"
    if not e.screenshot_decoded or not e.frame_consistency:
        return False, "FRAME_EVIDENCE_MISSING"
    vals=(e.clock_sec,e.matched_sec,e.score,e.peak_over_p75)
    if any(not isfinite(float(x)) for x in vals):
        return False, "NONFINITE_EVIDENCE"
    if abs(e.clock_sec-e.matched_sec)>30.0:
        return False, "CLOCK_FRAME_DRIFT"
    if e.score<0.63 or e.peak_over_p75<0.020:
        return False, "WEAK_OR_AMBIGUOUS_SCENE"
    return True, "SCENE_CANDIDATE_ONLY_BOUNDARY_QA_REQUIRED"
