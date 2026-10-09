#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only independent SigLIP semantic safety QA for real 892/886 examples.

A negative SigLIP logit must never silently skip a real cigarette candidate.
No pixel-mask approvals, no XML/video/Studio edits, no blur or publication.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import pathlib
import zipfile

SCHEMA="RG_CIGARETTE_SIGLIP_892_886_FAIL_CLOSED_V1"
INPUT_SCHEMA="RG_CIGARETTE_SIGLIP_REAL_PAIR_SHADOW_V1"
INPUT_SHA256="588189bc32cd683a6dce3488eb7816eaa912e34695ae063aed06e3ae52ed4ba8"
CASE_IDS=("POS_892_MOUTH","POS_892_HAND","NEG_892_MIC","NEG_892_MUG","NEG_886_MIC_MANUAL")
CIG=("cigarette_lit","cigarette_mouth")
OTHER=("microphone_logo","microphone","mug","hands","smoke_only","face")

def signal(logits):
    if not isinstance(logits,dict) or any(k not in logits for k in CIG+OTHER):
        return dict(signal="UNVERIFIED",action="REVIEW_REQUIRED",margin=None,
                    may_skip_blur=False,release_allowed=False)
    if any(type(v) not in (int,float) or abs(v)>100 for v in logits.values()):
        raise ValueError("invalid uncalibrated image-text logit")
    margin=round(max(logits[k] for k in CIG)-max(logits[k] for k in OTHER),5)
    if margin>=.015:label="CIGARETTE_CANDIDATE"
    elif margin<=-.020:label="OTHER_OBJECT_CANDIDATE"
    else:label="AMBIGUOUS_CIGARETTE_MAY_BE_PRESENT"
    # All scores require review when masking an already detected thin object;
    # low score cannot excuse skipping a real cigarette.
    return dict(signal=label,action="REVIEW_REQUIRED",margin=margin,
                may_skip_blur=False,release_allowed=False)

def exact_886_microphone_negative(ref_id,actual_crop_sha256,approved_sha256):
    # Limited to the exact human-reviewed microphone reference, NOT a
    # stream-886-wide exemption, even if another real cigarette is present.
    return (ref_id=="NEG_886_MIC_MANUAL"
            and bool(approved_sha256)
            and approved_sha256==actual_crop_sha256)

def assess_zip(src):
    data=pathlib.Path(src).read_bytes()
    if hashlib.sha256(data).hexdigest()!=INPUT_SHA256:
        raise ValueError("Five-example source ZIP differs from pinned reference")
    with zipfile.ZipFile(src) as z:
        if z.testzip() is not None:raise ValueError("Damaged source archive")
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError("Duplicate source members")
        if any(".." in pathlib.PurePosixPath(n).parts or pathlib.PurePosixPath(n).is_absolute()
               for n in names):raise ValueError("Unsafe source ZIP path")
        meta=json.loads(z.read("summary.json"))
        if meta.get("schema")!=INPUT_SCHEMA or meta.get("production_approved") is not False:
            raise ValueError("Unexpected SigLIP evidence schema or release contract")
        if tuple(x["id"] for x in meta["gold_cases"])!=CASE_IDS:
            raise ValueError("Unexpected five verified cases")
        if meta.get("positive_cases")!=2 or meta.get("negative_cases")!=3:
            raise ValueError("Wrong ground-truth group sizes")
        mic_bytes=z.read("crops/NEG_886_MIC_MANUAL_crop.jpg")
        mic_sha=hashlib.sha256(mic_bytes).hexdigest()
        records=[]
        for c in meta["gold_cases"]:
            rec=signal(c["result"]["prompt_logits"])
            ref=c["id"]
            digest=hashlib.sha256(z.read("crops/"+ref+"_crop.jpg")).hexdigest()
            known=exact_886_microphone_negative(ref,digest,mic_sha)
            records.append(dict(id=ref,human_label=c["human_label"],
                                observed_margin=rec["margin"],signal=rec["signal"],
                                exact_negative_reference=known,
                                action="KNOWN_NEGATIVE_REFERENCE_VETO" if known else "REVIEW_REQUIRED",
                                may_skip_blur=False,automatic_blur_allowed=False))
    if (records[0]["signal"]!="CIGARETTE_CANDIDATE"
        or records[1]["signal"]!="AMBIGUOUS_CIGARETTE_MAY_BE_PRESENT"
        or any(x["signal"]!="OTHER_OBJECT_CANDIDATE" for x in records[2:])
        or not records[-1]["exact_negative_reference"]):
        raise RuntimeError("Actual 892/886 five-reference semantic regression")
    return dict(schema=SCHEMA,status="FIVE_CASE_AUDITED_NOT_CALIBRATED",
                cases=records,
                reference_true_cigarette_mouth_flagged=True,
                reference_true_cigarette_hand_ambiguous_requires_review=True,
                known_negative_886_scoped_to_exact_crop=True,
                all_13_SAM2_frames_semantically_verified=False,
                full_886_negative_video_tested=False,
                cigarette_only_masks_verified=False,
                auto_blur_allowed=False,
                release_allowed=False,
                studio_modified=False,premiere_XML_modified=False,
                original_audio_modified=False,quarantine_886_5_modified=False)

def selftest():
    base={k:0.0 for k in CIG+OTHER}
    positive=dict(base,cigarette_mouth=.16,face=.135)
    hand=dict(base,cigarette_mouth=.09,hands=.10)
    microphone=dict(base,cigarette_mouth=.017,face=.055)
    assert signal(positive)["signal"]=="CIGARETTE_CANDIDATE"
    assert signal(hand)["signal"]=="AMBIGUOUS_CIGARETTE_MAY_BE_PRESENT"
    assert signal(microphone)["signal"]=="OTHER_OBJECT_CANDIDATE"
    for x in [positive,hand,microphone,{}]:
        assert signal(x)["action"]=="REVIEW_REQUIRED"
        assert signal(x)["release_allowed"] is False
        assert signal(x)["may_skip_blur"] is False
    assert exact_886_microphone_negative("NEG_886_MIC_MANUAL","hash","hash")
    assert not exact_886_microphone_negative("NEG_886_MIC_MANUAL","wrong","hash")
    assert not exact_886_microphone_negative("POS_892_HAND","hash","hash")
    print("RG_SIGLIP_FIVE_REAL_CASES_FAIL_CLOSED_SELFTEST: PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--zip",type=pathlib.Path)
    a=p.parse_args()
    if a.self_test:selftest()
    elif a.zip:print(json.dumps(assess_zip(a.zip),ensure_ascii=False,indent=2))
    else:p.error("--self-test or --zip required")

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("RG_SIGLIP_SEMANTIC_GATE_STOPPED: "+str(exc))
        raise SystemExit(2)
