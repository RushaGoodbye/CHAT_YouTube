#!/usr/bin/env python3
"""Classify captured Telegram updates without new polling or network access.

A link to a public Telegram post does NOT contain Bot API file_ids.
Fail closed until an authorized Telegram bot receives actual media.
Never log bot file IDs, original message contents or personal chat IDs.
"""
import argparse
import json
import re
from urllib.parse import urlsplit

class IngressError(ValueError):
    pass

LINK = re.compile(r"https://(?:t\.me|telegram\.me)/(?:s/)?[A-Za-z_][A-Za-z0-9_]{3,}/[0-9]{1,15}(?:\?[^\s<>]*)?",re.I)

def classify(message):
    if not isinstance(message,dict):
        raise IngressError("INVALID_MESSAGE")
    video=message.get("video")
    doc=message.get("document")
    media_group=message.get("media_group_id")
    if media_group is not None and (not isinstance(media_group,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",media_group)):
        raise IngressError("INVALID_MEDIA_GROUP")
    text=message.get("text")
    caption=message.get("caption")
    if text is not None and not isinstance(text,str):
        raise IngressError("INVALID_TEXT")
    if caption is not None and not isinstance(caption,str):
        raise IngressError("INVALID_CAPTION")
    if video is not None and not isinstance(video,dict):
        raise IngressError("INVALID_VIDEO")
    if doc is not None and not isinstance(doc,dict):
        raise IngressError("INVALID_DOCUMENT")
    if video is not None and doc is not None:
        raise IngressError("MULTIPLE_PRIMARY_MEDIA")
    origin = message.get("forward_origin")
    if origin is not None and not isinstance(origin,dict):
        raise IngressError("INVALID_FORWARD_ORIGIN")
    url_match=LINK.search(text or caption or "")
    if video is not None:
        fid=video.get("file_id")
        uid=video.get("file_unique_id")
        if not isinstance(fid,str) or not fid or not isinstance(uid,str) or not uid:
            raise IngressError("VIDEO_IDS_MISSING")
        result="ACTUAL_VIDEO"
    elif doc is not None:
        mime=doc.get("mime_type")
        fid=doc.get("file_id")
        if isinstance(mime,str) and mime.startswith("video/"):
            if not isinstance(fid,str) or not fid:
                raise IngressError("DOCUMENT_FILE_ID_MISSING")
            result="VIDEO_AS_DOCUMENT"
        else:
            result="OTHER_DOCUMENT"
    elif url_match:
        result="LINK_ONLY"
    elif message.get("photo"):
        result="PHOTO_ONLY"
    else:
        result="NO_MEDIA"
    return {
        "status":result,
        "contains_actual_video":result in ("ACTUAL_VIDEO","VIDEO_AS_DOCUMENT"),
        "source_link_present":bool(url_match),
        "media_group_present":bool(media_group),
        "forward_origin_present":bool(origin),
        "original_video_verified":False,
        "public_publication":"OFF",
    }

def inspect_updates(updates):
    if not isinstance(updates,list) or len(updates)>1000:
        raise IngressError("INVALID_UPDATES")
    counts={}
    for item in updates:
        if not isinstance(item,dict): raise IngressError("INVALID_UPDATE")
        msg=item.get("message") or item.get("edited_message")
        if msg is None: continue
        label=classify(msg)["status"]
        counts[label]=counts.get(label,0)+1
    return {"status":"READ_ONLY_INGRESS_SUMMARY",
            "counts":dict(sorted(counts.items())),
            "original_video_verified":False,
            "public_publication":"OFF"}

def selftest():
    old=[
        {"message":{"message_id":141,"text":"https://t.me/supernova_plus/62837?utm_source=chatgpt.com"}},
        {"message":{"message_id":143,"text":"https://t.me/supernova_plus/62837?utm_source=chatgpt.com"}},
    ]
    summary=inspect_updates(old)
    assert summary["counts"]=={"LINK_ONLY":2}
    assert summary["original_video_verified"] is False
    actual={"video":{"file_id":"SECRET_FILE_ID","file_unique_id":"SECRET_UID"},
            "media_group_id":"group-1","forward_origin":{"type":"channel"}}
    a=classify(actual)
    assert a["status"]=="ACTUAL_VIDEO" and a["media_group_present"]
    assert "SECRET" not in json.dumps(a)
    hybrid={"text":"https://t.me/supernova_plus/62837",
            "video":{"file_id":"x","file_unique_id":"y"}}
    assert classify(hybrid)["status"]=="ACTUAL_VIDEO"
    for bad in [
        {"text":123},
        {"video":{"file_id":"x"}},
        {"video":"not-dict"},
        {"media_group_id":"../bad"},
        {"video":{"file_id":"x","file_unique_id":"y"},"document":{"file_id":"z"}},
    ]:
        try:classify(bad)
        except IngressError:pass
        else:raise AssertionError("UNSAFE_MESSAGE_ACCEPTED")
    assert inspect_updates([])["counts"]=={}
    print("INGRESS_TWO_LINK_ONLY_MESSAGES_PASS")
    print("INGRESS_REAL_VIDEO_WITHOUT_SECRET_LEAK_PASS")
    print("INGRESS_MALFORMED_MESSAGES_FAIL_CLOSED_PASS")
    print("INGRESS_PUBLICATION_OFF_PASS")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("action",choices=["selftest","audit"])
    ap.add_argument("--file")
    args=ap.parse_args()
    if args.action=="selftest":selftest();return
    from pathlib import Path
    path=Path(args.file or "")
    if not args.file or path.is_symlink() or not path.is_file() or path.stat().st_size>2_000_000:
        raise SystemExit("UNSAFE_CAPTURE_FILE")
    try:
        data=json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data,dict):data=data.get("updates")
        out=inspect_updates(data)
        print(json.dumps(out,sort_keys=True))
    except (IngressError,ValueError,TypeError,OSError,UnicodeError):
        print(json.dumps({"status":"SAFE_STOP","original_video_verified":False,"public_publication":"OFF"}))
        raise SystemExit(2)

if __name__=="__main__":main()
