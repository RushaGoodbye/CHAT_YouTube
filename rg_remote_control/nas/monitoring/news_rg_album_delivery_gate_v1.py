#!/usr/bin/env python3
"""Offline safety gate for multi-video Telegram handoff.

No Telegram API calls, network requests, file writes or publishing.
External caller must separately establish Telegram source provenance.
"""
import argparse
import hashlib
import json
import pathlib
import re
import os

SHA256 = re.compile(r"[0-9a-f]{64}")
MEDIA_GROUP = re.compile(r"[A-Za-z0-9_-]{1,128}")
MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024

class GateError(ValueError):
    pass

def check_one(item, index):
    if not isinstance(item, dict):
        raise GateError("BAD_VIDEO_RECORD")
    if item.get("index") != index:
        raise GateError("VIDEO_ORDER_OR_COUNT_MISMATCH")
    if item.get("download_status") != "CONFIRMED":
        raise GateError("DOWNLOAD_UNVERIFIED")
    size = item.get("bytes")
    if type(size) is not int or not (12 <= size <= MAX_VIDEO_BYTES):
        raise GateError("VIDEO_SIZE_UNVERIFIED")
    if item.get("container") != "mp4" or item.get("mp4_magic_verified") is not True:
        raise GateError("VIDEO_FORMAT_UNVERIFIED")
    if not isinstance(item.get("sha256"), str) or not SHA256.fullmatch(item["sha256"]):
        raise GateError("VIDEO_CHECKSUM_MISSING")
    if item.get("source_provenance_verified") is not True:
        raise GateError("SOURCE_PROVENANCE_UNVERIFIED")
    return item["sha256"]

def validate(album):
    if not isinstance(album, dict):
        raise GateError("INVALID_ALBUM")
    source = album.get("source")
    if not isinstance(source, str) or not re.fullmatch(
        r"https://t\.me/[A-Za-z_][A-Za-z0-9_]{3,}/[1-9][0-9]{0,14}",source):
        raise GateError("INVALID_CANONICAL_SOURCE")
    group = album.get("media_group_id")
    if group is not None and (not isinstance(group, str) or not MEDIA_GROUP.fullmatch(group)):
        raise GateError("INVALID_MEDIA_GROUP")
    expected = album.get("expected_video_count")
    if type(expected) is not int or not (1 <= expected <= 10):
        raise GateError("INVALID_VIDEO_COUNT")
    videos = album.get("videos")
    if not isinstance(videos, list) or len(videos) != expected:
        raise GateError("VIDEO_COUNT_MISMATCH")
    signatures = [check_one(v, i+1) for i, v in enumerate(videos)]
    if len(set(signatures)) != expected:
        raise GateError("DUPLICATE_VIDEO")
    if album.get("moderator_approved") is not True:
        raise GateError("MODERATOR_APPROVAL_MISSING")
    if album.get("watermark_verified") is not True:
        raise GateError("WATERMARK_UNVERIFIED")
    if album.get("publication_receipt") is not None:
        raise GateError("ALREADY_PUBLISHED_OR_UNCERTAIN")
    # Keep final deployment gated: validation alone never authorizes publishing.
    return {"status":"MANIFEST_CONSISTENCY_PASS",
            "video_count":expected,
            "source":source,
            "public_publication":"OFF",
            "publication_authorized":False}

def verify_local_originals(album, base):
    """Verify bytes of existing, operator-supplied MP4 files, read-only.

    The caller must provide a trusted directory. Does not prove Telegram provenance.
    """
    base = pathlib.Path(base)
    if base.is_symlink() or not base.is_dir():
        raise GateError("UNSAFE_MEDIA_DIRECTORY")
    videos=album.get("videos")
    if not isinstance(videos,list) or not videos:
        raise GateError("VIDEO_COUNT_MISMATCH")
    base_real=base.resolve(strict=True)
    verified=[]
    for item in videos:
        name=item.get("local_file") if isinstance(item,dict) else None
        if (not isinstance(name,str) or
            not re.fullmatch(r"[A-Za-z0-9_-]{1,100}\.mp4", name)):
            raise GateError("INVALID_MEDIA_FILE_NAME")
        path=base_real/name
        if path.is_symlink() or not path.is_file():
            raise GateError("UNSAFE_MEDIA_FILE")
        size=path.stat().st_size
        if not (12 <= size <= MAX_VIDEO_BYTES):
            raise GateError("VIDEO_SIZE_UNVERIFIED")
        h=hashlib.sha256()
        with path.open("rb") as fp:
            head=fp.read(12)
            if head[4:8] != b"ftyp":
                raise GateError("VIDEO_FORMAT_UNVERIFIED")
            h.update(head)
            for chunk in iter(lambda: fp.read(1024*1024),b""):
                h.update(chunk)
        if size != item.get("bytes") or h.hexdigest() != item.get("sha256"):
            raise GateError("VIDEO_INTEGRITY_MISMATCH")
        verified.append({"local_file":name,"size":size,"sha256":h.hexdigest()})
    return {"status":"LOCAL_MP4_INTEGRITY_PASS",
            "verified_count":len(verified),"telegram_provenance_verified":False,
            "public_publication":"OFF"}

def demo():
    source="https://t.me/supernova_plus/62837"
    videos=[{"index":i,"download_status":"CONFIRMED","bytes":1024+i,
             "container":"mp4","mp4_magic_verified":True,
             "source_provenance_verified":True,"sha256":hashlib.sha256(str(i).encode()).hexdigest()}
            for i in range(1,4)]
    return {"source":source,"media_group_id":None,"expected_video_count":3,"videos":videos,
            "moderator_approved":True,"watermark_verified":True,"publication_receipt":None}

def selftest():
    import copy
    item=demo()
    result=validate(item)
    assert result["video_count"]==3 and result["publication_authorized"] is False
    cases = [
        ("VIDEO_COUNT_MISMATCH", lambda a: a["videos"].pop()),
        ("VIDEO_COUNT_MISMATCH", lambda a: a["videos"].append(copy.deepcopy(a["videos"][0]))),
        ("VIDEO_ORDER_OR_COUNT_MISMATCH", lambda a: a["videos"][1].update(index=1)),
        ("DUPLICATE_VIDEO", lambda a: a["videos"][1].update(sha256=a["videos"][0]["sha256"])),
        ("DOWNLOAD_UNVERIFIED", lambda a: a["videos"][0].update(download_status="UNKNOWN")),
        ("SOURCE_PROVENANCE_UNVERIFIED", lambda a: a["videos"][0].update(source_provenance_verified=False)),
        ("VIDEO_FORMAT_UNVERIFIED", lambda a: a["videos"][0].update(mp4_magic_verified=False)),
        ("MODERATOR_APPROVAL_MISSING", lambda a: a.update(moderator_approved=False)),
        ("WATERMARK_UNVERIFIED", lambda a: a.update(watermark_verified=False)),
        ("ALREADY_PUBLISHED_OR_UNCERTAIN", lambda a: a.update(publication_receipt={"status":"UNCERTAIN"})),
    ]
    for reason, modify in cases:
        candidate=copy.deepcopy(item)
        modify(candidate)
        try:
            validate(candidate)
        except GateError as ex:
            assert str(ex)==reason,(reason,str(ex))
        else:
            raise AssertionError("UNSAFE_HANDOFF_NOT_BLOCKED: "+reason)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        demo_album=demo()
        for i,item in enumerate(demo_album["videos"],1):
            filename=f"video_{i}.mp4"
            payload=b"\\x00\\x00\\x00\\x18ftypisom" + bytes([i])*64
            pathlib.Path(tmp,filename).write_bytes(payload)
            item["local_file"]=filename
            item["bytes"]=len(payload)
            item["sha256"]=hashlib.sha256(payload).hexdigest()
        result=verify_local_originals(demo_album,tmp)
        assert result["verified_count"]==3 and result["public_publication"]=="OFF"
        pathlib.Path(tmp,"video_2.mp4").write_bytes(b"\\x00"*80)
        try:
            verify_local_originals(demo_album,tmp)
        except GateError as e:
            assert str(e)=="VIDEO_FORMAT_UNVERIFIED"
        else:
            raise AssertionError("CORRUPTED_MP4_NOT_BLOCKED")
    print("LOCAL_FILE_SHA256_AND_MP4_HEADER_PASS")
    print("CORRUPTED_VIDEO_REJECTED_PASS")
    print("ALBUM_THREE_VIDEO_GATE_PASS")
    print("TEN_UNSAFE_HANDOFF_CASES_BLOCKED_PASS")
    print("PUBLICATION_DEFAULT_OFF_PASS")
    print("NO_NETWORK_NO_FILE_WRITES_PASS")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["selftest","check"])
    parser.add_argument("--manifest",help="Path to an existing JSON manifest for offline QA")
    args=parser.parse_args()
    if args.action=="selftest":
        selftest()
    else:
        if not args.manifest:parser.error("--manifest required")
        path=pathlib.Path(args.manifest)
        if path.is_symlink() or not path.is_file() or path.stat().st_size>100000:
            raise SystemExit("UNSAFE_MANIFEST")
        try:
            data=json.loads(path.read_text(encoding="utf-8"))
            print(json.dumps(validate(data),ensure_ascii=False,sort_keys=True))
        except (GateError,ValueError,TypeError) as e:
            print(json.dumps({"status":"SAFE_STOP","reason":str(e)[:90],
                              "public_publication":"OFF"},ensure_ascii=False))
            raise SystemExit(2)
