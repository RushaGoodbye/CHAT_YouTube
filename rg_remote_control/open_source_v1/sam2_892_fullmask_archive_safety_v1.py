#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only, fail-closed semantic-review gate for real 892 SAM2 full-mask ZIP.

Never changes videos, XML, Studio, model or audio. No blur or publish action.
Python standard library only. Binary pixel-ground-truth verification is a
separate, human-reviewed requirement; a clean geometry gate is NOT approval.
"""
from __future__ import annotations
import argparse, datetime, json, pathlib, struct, zipfile

SCHEMA="RG_SAM2_892_FULL_MASK_ARCHIVE_SAFETY_GATE_V1"
EXPECTED_REPORT="RG_SAM2_892_REAL_VIDEO_TRACK_SHADOW_V2_FULL_MASK"
SOURCE="RG_SAM2_892_REAL_MOTION_FULL_MASK_V2.zip"
SIZE_XY=(1920,1080)
FRAME_COUNT=13
MAX_MEMBER_BYTES=10_000_000

def analyze(rows):
    if len(rows)!=FRAME_COUNT:raise ValueError("13 frames required")
    signals=[]
    prior=None
    for idx,row in enumerate(rows):
        if row.get("frame_idx")!=idx:raise ValueError("frame index mismatch")
        p=row.get("pixels")
        if type(p) is not int or p<0:raise ValueError("invalid integer mask area")
        if row.get("automatic_blur_allowed") is not False:
            raise ValueError("unexpected automatic blur permission on frame")
        if p==0:
            signals.append(dict(frame=idx,code="EMPTY_MASK",severity="STOP"))
        if p>5000:
            signals.append(dict(frame=idx,code="LARGE_MASK",severity="STOP"))
        if prior is not None and p>0 and prior>0:
            ratio=p/prior
            if ratio>1.40:
                signals.append(dict(frame=idx,previous_frame=idx-1,
                                    code="MASK_AREA_GROWTH_OVER_40_PERCENT",
                                    area_before=prior,area_after=p,
                                    change_percent=round((ratio-1)*100,2),
                                    severity="REVIEW_REQUIRED"))
            if ratio<0.60:
                signals.append(dict(frame=idx,previous_frame=idx-1,
                                    code="MASK_AREA_DROP_OVER_40_PERCENT",
                                    area_before=prior,area_after=p,
                                    change_percent=round((ratio-1)*100,2),
                                    severity="REVIEW_REQUIRED"))
        prior=p
    return signals

def inspect_zip(file):
    archive=pathlib.Path(file)
    if not archive.is_file():raise FileNotFoundError(str(archive))
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError("duplicate ZIP paths")
        if any(pathlib.PurePosixPath(name).is_absolute() or ".." in pathlib.PurePosixPath(name).parts
               for name in names):raise ValueError("unsafe ZIP member path")
        for inf in z.infolist():
            if inf.file_size>MAX_MEMBER_BYTES:raise ValueError("oversize ZIP member")
        if z.testzip() is not None:raise ValueError("bad ZIP CRC")
        d=json.loads(z.read("report.json").decode("utf-8"))
        if d.get("schema")!=EXPECTED_REPORT or d.get("video")!="892":
            raise ValueError("unexpected source stream/schema")
        if d.get("frames")!=FRAME_COUNT or d.get("fps")!=6:
            raise ValueError("unexpected frame count/fps")
        for k in ("release_allowed","automatic_blur_allowed","original_audio_modified",
                  "premiere_xml_modified","studio_modified","quarantine_886_5_modified"):
            if d.get(k) is not False:raise ValueError("unsafe release/media flag "+k)
        if d.get("full_resolution_binary_masks_saved") is not True:
            raise ValueError("masks not saved as full resolution")
        rows=d.get("frame_metrics")
        if not isinstance(rows,list):raise ValueError("frame_metrics missing")
        signals=analyze(rows)
        for i,row in enumerate(rows):
            expected=f"review_frames/FULL_MASK_{i:02d}_1920x1080.png"
            if row.get("full_mask_png")!=expected:raise ValueError("mask pathname mismatch")
            if expected not in names:raise ValueError("missing full binary mask")
            b=z.read(expected)
            if b[:8]!=b"\x89PNG\r\n\x1a\n":
                raise ValueError("invalid PNG signature")
            if len(b)<24 or struct.unpack(">II",b[16:24])!=SIZE_XY:
                raise ValueError("unexpected PNG dimensions")
        return dict(
            schema=SCHEMA,report_created_utc=d.get("created_at_utc"),
            frames=FRAME_COUNT,source_stream="892",source_zip=archive.name,
            mask_area_volatility_events=signals,
            volatility_event_count=len(signals),
            old_report_warning_frame_count=d.get("warning_frame_count"),
            original_static_roi_exit_informational=d.get("old_static_preview_exit_frame_count"),
            geometry_stability_pass=(len(signals)==0),
            verified_pixel_cigarette_only=False,
            semantic_identity_on_every_frame_proven=False,
            hand_face_smoke_exclusion_proven=False,
            production_release_allowed=False,automatic_blur_allowed=False,
            requires_human_frame_qa=True,
            note="A geometry pass is NOT object identity or blur approval; video/audio/XML unchanged."
        )

def selftest():
    def mk(areas):
        return [{"frame_idx":i,"pixels":v,"automatic_blur_allowed":False}
                for i,v in enumerate(areas)]
    base=[2005,2017,2176,2104,2994,1135,1817,1408,1517,1339,1071,1035,1004]
    flags=analyze(mk(base))
    expected=[(4,"MASK_AREA_GROWTH_OVER_40_PERCENT"),
              (5,"MASK_AREA_DROP_OVER_40_PERCENT"),
              (6,"MASK_AREA_GROWTH_OVER_40_PERCENT")]
    assert [(x["frame"],x["code"]) for x in flags]==expected
    assert analyze(mk([1500]*13))==[]
    try:
        analyze(mk([1000]*12))
    except ValueError:pass
    else:raise AssertionError("Missing-frame fail-closed regression broken")
    try:
        analyze([{"frame_idx":i,"pixels":1000,"automatic_blur_allowed":i==5}
                 for i in range(13)])
    except ValueError:pass
    else:raise AssertionError("Unsafe blur permission not rejected")
    print("RG_SAM2_892_13_FRAME_TEMPORAL_AREA_STRICT_QA_SELFTEST: PASS")

def main():
    ap=argparse.ArgumentParser(description="Offline cigarette mask QA, no GPU/no installs")
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--zip",type=pathlib.Path)
    args=ap.parse_args()
    if args.self_test:
        selftest()
    elif args.zip:
        print(json.dumps(inspect_zip(args.zip),ensure_ascii=False,indent=2))
    else:
        ap.error("--self-test or --zip required")
if __name__=="__main__":
    try:main()
    except Exception as ex:
        print("RG_SAM2_892_FULL_MASK_FAIL_CLOSED: "+str(ex))
        raise SystemExit(2)
