#!/usr/bin/env python3
"""Fail-closed launch readiness audit for RG Telegram video albums.

Read-only assessment. Never sends, publishes, downloads or modifies source data.
Selftests with synthetic evidence do not constitute production certification.
"""
import argparse
import json
import pathlib

REQUIRED = {
    "nas_runner_private_isolated": "RUNNER_PUBLIC_REPOSITORY_EXPOSURE",
    "source_album_membership_verified": "SOURCE_ALBUM_NOT_PROVEN",
    "original_three_videos_sha256_verified": "ORIGINAL_MEDIA_NOT_VERIFIED",
    "telegram_media_provenance_verified": "MEDIA_PROVENANCE_NOT_VERIFIED",
    "moderation_card_confirmed": "MODERATION_CARD_NOT_CONFIRMED",
    "human_approval_confirmed": "HUMAN_APPROVAL_MISSING",
    "watermark_file_and_position_verified": "WATERMARK_UNVERIFIED",
    "required_footer_verified": "MANDATORY_FOOTER_UNVERIFIED",
    "duplicate_publication_guard_verified": "IDEMPOTENCY_NOT_VERIFIED",
    "nas_backup_and_restore_drill_passed": "RECOVERY_NOT_VERIFIED",
    "bot_owner_single_polling_verified": "BOT_OWNER_NOT_VERIFIED",
    "live_telegram_health_fresh": "TELEGRAM_HEALTH_STALE",
}
EXPECTED_SOURCE = "https://t.me/supernova_plus/62837"

def assess(evidence):
    if not isinstance(evidence, dict):
        raise ValueError("INVALID_EVIDENCE")
    blockers = [reason for name,reason in REQUIRED.items() if evidence.get(name) is not True]
    if evidence.get("source_url") != EXPECTED_SOURCE:
        blockers.append("SOURCE_URL_UNVERIFIED")
    if evidence.get("source_video_count") != 3 or type(evidence.get("source_video_count")) is not int:
        blockers.append("SOURCE_VIDEO_COUNT_UNVERIFIED")
    if evidence.get("original_video_count") != 3 or type(evidence.get("original_video_count")) is not int:
        blockers.append("ORIGINAL_VIDEO_COUNT_UNVERIFIED")
    if evidence.get("public_publication") != "OFF":
        blockers.append("UNSAFE_PUBLICATION_FLAG")
    if evidence.get("secrets_in_artifacts") is not False:
        blockers.append("SECRETS_EXPOSURE_NOT_RULED_OUT")
    return {
        "status": "BLOCKED" if blockers else "PREPARED_FOR_SEPARATE_MANUAL_PILOT_REVIEW",
        "blockers": blockers,
        "checked": len(REQUIRED)+5,
        "publication_authorized": False,
        "public_publication": "OFF",
        "read_only": True,
    }

def selftest():
    bad = {"source_url":EXPECTED_SOURCE,"source_video_count":3,"original_video_count":0,
           "public_publication":"OFF","secrets_in_artifacts":False}
    result=assess(bad)
    assert result["status"]=="BLOCKED"
    assert "RUNNER_PUBLIC_REPOSITORY_EXPOSURE" in result["blockers"]
    assert "ORIGINAL_VIDEO_COUNT_UNVERIFIED" in result["blockers"]
    assert result["publication_authorized"] is False
    complete=dict(bad)
    complete.update({k:True for k in REQUIRED})
    complete["original_video_count"]=3
    prepared=assess(complete)
    assert prepared["status"]=="PREPARED_FOR_SEPARATE_MANUAL_PILOT_REVIEW"
    assert prepared["publication_authorized"] is False
    complete["public_publication"]="ON"
    assert "UNSAFE_PUBLICATION_FLAG" in assess(complete)["blockers"]
    complete["public_publication"]="OFF"
    complete["source_video_count"]=True
    assert "SOURCE_VIDEO_COUNT_UNVERIFIED" in assess(complete)["blockers"]
    print("RELEASE_READINESS_BLOCKERS_PASS")
    print("SIMULATED_COMPLETE_EVIDENCE_STILL_NO_PUBLICATION_PASS")
    print("UNSAFE_PUBLICATION_REJECTED_PASS")
    print("BOOLEAN_COUNT_REJECTED_PASS")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["selftest","assess"])
    parser.add_argument("--evidence")
    args=parser.parse_args()
    if args.action=="selftest":
        selftest()
    else:
        if not args.evidence:
            parser.error("--evidence is required")
        path=pathlib.Path(args.evidence)
        if path.is_symlink() or not path.is_file() or path.stat().st_size>100000:
            raise SystemExit("UNSAFE_EVIDENCE_PATH")
        try:
            evidence=json.loads(path.read_text(encoding="utf-8"))
            result=assess(evidence)
        except (ValueError,OSError,UnicodeError,TypeError):
            result={"status":"BLOCKED","blockers":["EVIDENCE_UNREADABLE"],
                    "public_publication":"OFF","publication_authorized":False}
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        if result["status"]=="BLOCKED":
            raise SystemExit(2)

if __name__=="__main__":
    main()
