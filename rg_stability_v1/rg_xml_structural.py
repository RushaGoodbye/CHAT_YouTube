"""Structural XML safety check, not a substitute for Premiere visual inspection."""
from __future__ import annotations
from pathlib import Path
import xml.etree.ElementTree as ET

def audit_premiere_xml(path:Path)->dict:
    path=Path(path)
    if not path.is_file() or path.stat().st_size==0:
        return {"status":"FAIL","errors":["XML_MISSING"],"checks":[]}
    try:
        root=ET.parse(str(path)).getroot()
    except (ET.ParseError,OSError,ValueError) as exc:
        return {"status":"FAIL","errors":["XML_PARSE_ERROR"],"checks":[]}
    clips=root.findall(".//clipitem")
    media=root.findall(".//file")
    video_tracks=root.findall(".//video/track")
    audio_tracks=root.findall(".//audio/track")
    invalid=[]
    for c in clips:
        st=c.findtext("start")
        en=c.findtext("end")
        if st is None or en is None:
            invalid.append("CLIP_BOUNDARY_MISSING")
        else:
            try:
                if int(st)<0 or int(en)<=int(st):invalid.append("CLIP_BOUNDARY_INVALID")
            except ValueError:invalid.append("CLIP_BOUNDARY_INVALID")
    checks=[
        {"name":"xml_parse","ok":True},
        {"name":"video_tracks_present","ok":bool(video_tracks)},
        {"name":"audio_tracks_present","ok":bool(audio_tracks)},
        {"name":"clips_present","ok":bool(clips)},
        {"name":"clip_boundaries_valid","ok":not invalid},
    ]
    errors=[x["name"].upper() for x in checks if not x["ok"]]+invalid
    # XML structure alone never proves a valid rendered preview or the correct speaker.
    return {"status":"REVIEW" if not errors else "FAIL","errors":errors,
            "checks":checks,"clip_count":len(clips),"video_tracks":len(video_tracks),
            "audio_tracks":len(audio_tracks),"file_refs":len(media),
            "premiere_visual_validation":False}
