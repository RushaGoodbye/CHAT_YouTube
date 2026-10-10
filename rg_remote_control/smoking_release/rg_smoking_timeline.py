"""Exact CFR Premiere source scope. Never infer identity from a basename."""
from __future__ import annotations
from fractions import Fraction
from pathlib import PureWindowsPath
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET
from rg_smoking_compliance import ReviewRequired


def path_identity(raw):
    parsed=urlparse(str(raw or ''))
    if parsed.scheme.lower()=='file':
        path=unquote(parsed.path)
        if parsed.netloc: path='//'+parsed.netloc+path
        elif len(path)>3 and path[0]=='/' and path[2]==':': path=path[1:]
    else: path=unquote(str(raw or ''))
    return str(PureWindowsPath(path)).casefold()


def file_definitions(root):
    definitions={}
    for node in root.findall('.//file'):
        fid=node.get('id'); path=node.findtext('pathurl')
        if not fid or not path: continue
        previous=definitions.get(fid)
        if previous is not None and path_identity(previous.findtext('pathurl'))!=path_identity(path):
            raise ReviewRequired('CONFLICTING_MEDIA_FILE_ID')
        if previous is None or len(ET.tostring(node))>len(ET.tostring(previous)):
            definitions[fid]=node
    return definitions


def rate(node, fallback=None):
    r=node.find('rate')
    if r is None:
        if fallback is not None: return fallback
        raise ReviewRequired('TIMELINE_RATE_MISSING')
    try:
        base=int(r.findtext('timebase'))
        if base<=0: raise ValueError()
        ntsc=r.findtext('ntsc')
        if ntsc not in ('TRUE','FALSE'): raise ValueError()
    except (ValueError,TypeError): raise ReviewRequired('TIMELINE_RATE_INVALID')
    return Fraction(base*1000,1001) if ntsc=='TRUE' else Fraction(base)


def integer(node,name):
    try:
        raw=node.findtext(name)
        value=int(raw)
        if str(value)!=raw.strip(): raise ValueError()
        return value
    except (TypeError,ValueError,AttributeError): raise ReviewRequired('TIMELINE_FRAME_INVALID:'+name)


def source_scope(xml_bytes, source_path, source_fps=Fraction(30), *, allow_timewarp_for_source_audit=False):
    root=ET.fromstring(xml_bytes)
    seq=root.find('sequence')
    if root.tag!='xmeml' or seq is None: raise ReviewRequired('XMEML_SEQUENCE_MISSING')
    fps=rate(seq)
    if fps!=source_fps: raise ReviewRequired('MIXED_OR_UNSUPPORTED_FRAME_RATE')
    definitions=file_definitions(root)
    clips=[]; mapping_issues=[]
    target=path_identity(source_path)
    for ti,track in enumerate(seq.findall('./media/video/track')):
        for clip in track.findall('clipitem'):
            file=clip.find('file')
            if file is None: raise ReviewRequired('VIDEO_MEDIA_FILE_MISSING')
            path=file.findtext('pathurl')
            if not path and file.get('id') in definitions:
                path=definitions[file.get('id')].findtext('pathurl')
            if not path: raise ReviewRequired('UNRESOLVED_VIDEO_MEDIA_REFERENCE')
            if path_identity(path)!=target: continue
            start,end,inside,outside=(integer(clip,k) for k in ('start','end','in','out'))
            if not (0<=start<end and 0<=inside<outside):
                raise ReviewRequired('TIMELINE_CLIP_BOUNDS_INVALID')
            if rate(clip,fps)!=source_fps:
                raise ReviewRequired('MIXED_OR_UNSUPPORTED_SOURCE_FRAME_RATE')
            speed_effect=any((f.findtext('effect/effectid') or '').lower() in ('timeremap','speed')
                   for f in clip.findall('filter'))
            if end-start!=outside-inside or speed_effect:
                mapping_issues.append(dict(clip_id=clip.get('id'),timeline_frames=end-start,
                    source_frames=outside-inside,speed_effect=speed_effect))
                if not allow_timewarp_for_source_audit:
                    raise ReviewRequired('TIMEWARP_REQUIRES_SEPARATE_REVIEW')
            clips.append(dict(track=ti,clip_id=clip.get('id'),timeline=[start,end],source=[inside,outside]))
    if not clips: raise ReviewRequired('EXACT_SOURCE_NOT_ON_TIMELINE')
    ranges=[]
    for a,b in sorted(c['source'] for c in clips):
        if ranges and a<=ranges[-1][1]: ranges[-1][1]=max(b,ranges[-1][1])
        else: ranges.append([a,b])
    return dict(fps_numerator=fps.numerator,fps_denominator=fps.denominator,
        timeline_frames=integer(seq,'duration'),clips=clips,ranges=ranges,
        unique_source_frames=sum(b-a for a,b in ranges),
        exact_timeline_mapping=not mapping_issues,mapping_issues=mapping_issues,
        purpose='SOURCE_AUDIT_ONLY' if mapping_issues else 'EXACT_CFR_SOURCE_SCOPE')
