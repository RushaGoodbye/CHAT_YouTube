"""Bounded, explicit error routing. Pure decisions; no background jobs."""
from __future__ import annotations

SAFE_QA_ONLY = frozenset({"POSTRUN_QA_FAILED","QA_REPORT_MISSING","TABLE_CONTRACT_FAILED"})
INPUT_ERRORS = frozenset({"VIDEO_MISSING","AUDIO_MISSING","SCREENSHOTS_MISSING","NAS_UNAVAILABLE"})
CRITICAL = frozenset({"OUTPUT_ARCHIVE_FAILED","XML_INTEGRITY_FAILED","SOURCE_CHANGED","DISK_FULL"})

def classify_failure(code:str, *, xml_verified:bool, manifest_complete:bool,
                     qa_failure_only:bool=False)->dict:
    code=str(code or "").upper().strip()
    if code in CRITICAL:
        return {"status":"STOP_QUEUE","action":"PRESERVE_OUTPUTS_AND_REVIEW",
                "automatic_video_restart":False}
    if code in SAFE_QA_ONLY and xml_verified and manifest_complete and qa_failure_only:
        return {"status":"REVIEW","action":"QA_ONLY_RECHECK_IN_STUDIO",
                "automatic_video_restart":False}
    if code in INPUT_ERRORS:
        return {"status":"SKIP_CURRENT","action":"MARK_INPUT_ERROR_CONTINUE_QUEUE",
                "automatic_video_restart":False}
    return {"status":"REVIEW","action":"MANUAL_DIAGNOSTIC",
            "automatic_video_restart":False}
