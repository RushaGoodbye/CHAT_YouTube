#!/usr/bin/env python3
"""Read-only Telegram Bot API update projection for original video albums.

Input: already captured getUpdates / webhook update dictionaries, supplied by
the SINGLE existing update owner. Does not poll, send, download, or persist.
Do not equate a public post URL with this Bot API media projection.
"""
import argparse
import json
import re

class AlbumError(ValueError):
    pass

def safe_int(value, name):
    if type(value) is not int or value <= 0:
        raise AlbumError("INVALID_" + name)
    return value

def project(updates, expected_chat=None, expected_group=None):
    if not isinstance(updates, list) or not (1 <= len(updates) <= 200):
        raise AlbumError("UNSAFE_UPDATES_INPUT")
    by_group = {}
    seen_updates = set()
    seen_messages = set()
    for update in updates:
        if not isinstance(update, dict):
            raise AlbumError("UNSAFE_UPDATE")
        update_id = safe_int(update.get("update_id"), "UPDATE_ID")
        if update_id in seen_updates:
            raise AlbumError("DUPLICATE_UPDATE_ID")
        seen_updates.add(update_id)
        msg = update.get("message")
        if not isinstance(msg, dict):
            continue
        chat = msg.get("chat")
        if not isinstance(chat, dict):
            raise AlbumError("UNSAFE_CHAT")
        chat_id = chat.get("id")
        if type(chat_id) is not int or chat_id == 0:
            raise AlbumError("INVALID_CHAT_ID")
        if expected_chat is not None and chat_id != expected_chat:
            continue
        group = msg.get("media_group_id")
        if group is None:
            continue
        if not isinstance(group, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", group):
            raise AlbumError("INVALID_MEDIA_GROUP_ID")
        if expected_group is not None and group != expected_group:
            continue
        mid = safe_int(msg.get("message_id"), "MESSAGE_ID")
        key = (chat_id, mid)
        if key in seen_messages:
            raise AlbumError("DUPLICATE_MESSAGE")
        seen_messages.add(key)
        video = msg.get("video")
        if not isinstance(video, dict):
            raise AlbumError("NON_VIDEO_ALBUM_MEMBER")
        file_id = video.get("file_id")
        file_unique_id = video.get("file_unique_id")
        if not isinstance(file_id, str) or not (1 <= len(file_id) <= 4096):
            raise AlbumError("VIDEO_FILE_ID_MISSING")
        if not isinstance(file_unique_id, str) or not (1 <= len(file_unique_id) <= 255):
            raise AlbumError("VIDEO_UNIQUE_ID_MISSING")
        size = video.get("file_size")
        if size is not None and (type(size) is not int or size <= 0):
            raise AlbumError("INVALID_VIDEO_FILE_SIZE")
        group_key = (chat_id, group)
        by_group.setdefault(group_key, []).append({
            "message_id": mid,
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "file_size": size,
            "caption_present": isinstance(msg.get("caption"), str),
            "forward_origin_present": isinstance(msg.get("forward_origin"), dict),
        })
    results = []
    for (chat_id, group), videos in sorted(by_group.items()):
        videos = sorted(videos, key=lambda d: d["message_id"])
        if len(videos) > 10:
            raise AlbumError("ALBUM_TOO_LARGE")
        if len({item["file_unique_id"] for item in videos}) != len(videos):
            raise AlbumError("REPEATED_VIDEO_FILE_UNIQUE_ID")
        results.append({
            "chat_id": chat_id,
            "media_group_id": group,
            "video_count_observed": len(videos),
            "video_message_ids": [v["message_id"] for v in videos],
            "distinct_file_unique_ids_count": len({v["file_unique_id"] for v in videos}),
            # The file_id is deliberately not printed or written by the CLI.
            "file_ids_available_in_memory": all(v["file_id"] for v in videos),
            "all_file_sizes_present": all(v["file_size"] is not None for v in videos),
            "source_provenance_verified": False,
            "complete_album_verified": False,
            "ready_to_publish": False,
        })
    return results

def private_video_refs(updates, *, expected_chat, expected_group, expected_count):
    """For trusted in-process single owner only; never log or serialize return value.

    All members must be present in provided capture, and their identifiers must
    be unique. Actual Bot API getFile still must be performed by current owner.
    """
    if type(expected_chat) is not int or expected_chat == 0:
        raise AlbumError("INVALID_EXPECTED_CHAT")
    if not isinstance(expected_group, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",expected_group):
        raise AlbumError("INVALID_EXPECTED_MEDIA_GROUP")
    if type(expected_count) is not int or not (1 <= expected_count <= 10):
        raise AlbumError("INVALID_EXPECTED_COUNT")
    result=project(updates,expected_chat=expected_chat,expected_group=expected_group)
    if len(result) != 1 or result[0]["video_count_observed"] != expected_count:
        raise AlbumError("INCOMPLETE_MEDIA_GROUP")
    ids=[]
    for item in updates:
        m=item.get("message") if isinstance(item,dict) else None
        if not isinstance(m,dict):
            continue
        if m.get("media_group_id") != expected_group or (m.get("chat") or {}).get("id") != expected_chat:
            continue
        ids.append((m["message_id"],m["video"]["file_id"]))
    ids.sort()
    if len(ids) != expected_count:
        raise AlbumError("INCOMPLETE_MEDIA_GROUP")
    return tuple(file_id for _,file_id in ids)

def fixture():
    return [
        {"update_id": i+500,
         "message": {
             "message_id": i+100,
             "chat": {"id": 1234, "type": "private"},
             "media_group_id": "group_001",
             "video": {"file_id": f"secret_file_{i}", "file_unique_id":f"unique_{i}", "file_size":1024+i},
         }} for i in (3,1,2)
    ]

def selftest():
    import copy
    data = fixture()
    result=project(data,expected_chat=1234,expected_group="group_001")
    assert len(result)==1 and result[0]["video_count_observed"]==3
    assert result[0]["video_message_ids"]==[101,102,103]
    assert result[0]["ready_to_publish"] is False
    assert "secret_file" not in json.dumps(result)
    assert not any("unique_" + str(i) in json.dumps(result) for i in (1,2,3))
    assert result[0]["distinct_file_unique_ids_count"] == 3
    assert project(data,expected_chat=99)==[]
    refs=private_video_refs(data,expected_chat=1234,expected_group="group_001",expected_count=3)
    assert refs==("secret_file_1","secret_file_2","secret_file_3")
    try: private_video_refs(data[:2],expected_chat=1234,expected_group="group_001",expected_count=3)
    except AlbumError as e: assert str(e)=="INCOMPLETE_MEDIA_GROUP"
    else: raise AssertionError("INCOMPLETE_MEDIA_GROUP_ACCEPTED")
    unsafe_cases=[
        ("DUPLICATE_UPDATE_ID",lambda d:d[1].update(update_id=d[0]["update_id"])),
        ("DUPLICATE_MESSAGE",lambda d:d[1]["message"].update(message_id=d[0]["message"]["message_id"])),
        ("NON_VIDEO_ALBUM_MEMBER",lambda d:d[1]["message"].pop("video")),
        ("INVALID_MEDIA_GROUP_ID",lambda d:d[1]["message"].update(media_group_id="../../")),
        ("VIDEO_FILE_ID_MISSING",lambda d:d[1]["message"]["video"].update(file_id="")),
        ("VIDEO_UNIQUE_ID_MISSING",lambda d:d[1]["message"]["video"].update(file_unique_id="")),
        ("REPEATED_VIDEO_FILE_UNIQUE_ID",lambda d:d[1]["message"]["video"].update(file_unique_id=d[0]["message"]["video"]["file_unique_id"])),
        ("INVALID_VIDEO_FILE_SIZE",lambda d:d[1]["message"]["video"].update(file_size=0)),
    ]
    for reason, mutate in unsafe_cases:
        bad=copy.deepcopy(data)
        mutate(bad)
        try: project(bad)
        except AlbumError as e:
            assert str(e)==reason,(reason,str(e))
        else: raise AssertionError("UNSAFE_INPUT_PASSED_" + reason)
    print("BOT_API_ALBUM_THREE_VIDEO_PROJECTION_PASS")
    print("BOT_API_EIGHT_INVALID_INPUTS_REJECTED_PASS")
    print("BOT_API_FILE_IDS_REDACTED_PASS")
    print("BOT_API_UNIQUE_IDS_REDACTED_PASS")
    print("BOT_API_PRIVATE_FILE_REFS_COMPLETE_GROUP_ONLY_PASS")
    print("BOT_API_ALBUM_COMPLETENESS_REQUIRES_OWNER_CONFIRMATION_PASS")
    print("NO_TELEGRAM_NETWORK_OR_SECOND_POLLER_PASS")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["selftest","project"])
    parser.add_argument("--input-file")
    parser.add_argument("--chat-id",type=int)
    args=parser.parse_args()
    if args.action=="selftest":
        selftest()
        return
    if not args.input_file:
        parser.error("--input-file required")
    from pathlib import Path
    p=Path(args.input_file)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>2_000_000:
        raise SystemExit("UNSAFE_CAPTURE_FILE")
    try:
        data=json.loads(p.read_text(encoding="utf-8-sig"))
        if isinstance(data,dict):
            data=data.get("updates")
        result=project(data,expected_chat=args.chat_id)
    except (AlbumError, ValueError, UnicodeError, OSError, RecursionError) as e:
        reason=str(e) if isinstance(e,AlbumError) else "UNREADABLE_CAPTURE"
        print(json.dumps({"status":"SAFE_STOP","reason":reason,"public_publication":"OFF"}))
        raise SystemExit(2)
    except TypeError:
        print(json.dumps({"status":"SAFE_STOP","reason":"UNSAFE_CAPTURE_SCHEMA","public_publication":"OFF"}))
        raise SystemExit(2)
    print(json.dumps({"status":"READ_ONLY_PROJECTION","albums":result,
                      "public_publication":"OFF"},ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
