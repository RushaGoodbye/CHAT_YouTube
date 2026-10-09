"""Video-only candidate XML replacement, preserving resolved audio and motion.

No model is imported here. Derivatives use source coordinates and CFR timing.
An unreviewed candidate is not a publication decision. 886_5 is always withheld.
"""
from __future__ import annotations
import copy
from fractions import Fraction
import hashlib
from pathlib import Path
from urllib.parse import unquote,urlparse
import xml.etree.ElementTree as ET
from rg_smoking_compliance import ReviewRequired,sha256_file,valid_sha
from rg_smoking_timeline import file_definitions,path_identity,integer,rate

TICKS_PER_SECOND=254016000000


def local_path(raw):
    parsed=urlparse(str(raw))
    if parsed.scheme.lower()!='file': return Path(unquote(str(raw)))
    value=unquote(parsed.path)
    if parsed.netloc: value='//'+parsed.netloc+value
    elif len(value)>3 and value[0]=='/' and value[2]==':': value=value[1:]
    return Path(value)


def resolved_audio_hash(xml):
    root=ET.fromstring(xml) if isinstance(xml,(bytes,str)) else xml
    definitions=file_definitions(root)
    audio=root.find('./sequence/media/audio')
    if audio is None: return hashlib.sha256(b'NO_AUDIO_TRACKS').hexdigest()
    audio=copy.deepcopy(audio)
    for parent in audio.iter():
        for file in list(parent):
            if file.tag!='file': continue
            definition=definitions.get(file.get('id'))
            if definition is None and not file.findtext('pathurl'):
                raise ReviewRequired('UNRESOLVED_AUDIO_FILE_REFERENCE')
            full=copy.deepcopy(definition if definition is not None else file)
            full.attrib.pop('id',None)
            position=list(parent).index(file)
            parent.remove(file); parent.insert(position,full)
    return hashlib.sha256(ET.tostring(audio,encoding='utf-8')).hexdigest()


def candidate_bytes(original,derivatives,dialogue):
    if dialogue=='886_5': raise ReviewRequired('886_5_QUARANTINED_NO_EXPORT')
    if not isinstance(derivatives,list):
        raise ReviewRequired('VERIFIED_VIDEO_DERIVATIVES_REQUIRED')
    if not derivatives:
        # Fully verified negatives preserve the original XML byte for byte.
        # Independent source review is still mandatory in the delivery gate.
        return original
    root=ET.fromstring(original)
    definitions=file_definitions(root)
    fps=rate(root.find('sequence'))
    if fps!=Fraction(30): raise ReviewRequired('ONLY_EXACT_CFR_30_SUPPORTED')
    original_audio=resolved_audio_hash(root)
    identities={}
    for item in derivatives:
        if not isinstance(item,dict) or not valid_sha(item.get('sha256')):
            raise ReviewRequired('DERIVATIVE_IDENTITY_MISSING')
        a,b=item.get('source_range_frames',[None,None])
        if type(a) is not int or type(b) is not int or not 0<=a<b:
            raise ReviewRequired('DERIVATIVE_SOURCE_RANGE_INVALID')
        if item.get('fps_numerator')!=30 or item.get('fps_denominator')!=1 or item.get('frames')!=b-a:
            raise ReviewRequired('DERIVATIVE_TIMING_MISMATCH')
        if item.get('has_audio') is not False:
            raise ReviewRequired('DERIVATIVE_MUST_BE_VIDEO_ONLY')
        src=path_identity(item['source_path']); dst=path_identity(item['path'])
        if src==dst: raise ReviewRequired('SOURCE_MEDIA_OVERWRITE_FORBIDDEN')
        if dst in identities: raise ReviewRequired('DUPLICATE_DERIVATIVE_PATH')
        identities[dst]=item
    count=0; used=set()
    for clip in root.findall('./sequence/media/video/track/clipitem'):
        file=clip.find('file')
        if file is None: raise ReviewRequired('VIDEO_FILE_MISSING')
        definition=definitions.get(file.get('id'),file)
        source=definition.findtext('pathurl') or file.findtext('pathurl')
        if not source: raise ReviewRequired('VIDEO_FILE_REFERENCE_UNRESOLVED')
        matching=[d for d in derivatives if path_identity(d['source_path'])==path_identity(source)]
        if not matching: continue
        inside,outside=(integer(clip,n) for n in ('in','out'))
        start,end=(integer(clip,n) for n in ('start','end'))
        if outside-inside!=end-start or rate(clip,fps)!=fps:
            raise ReviewRequired('TIMEWARP_REQUIRES_SEPARATE_REVIEW')
        matches=[d for d in matching if d['source_range_frames'][0]<=inside<outside<=d['source_range_frames'][1]]
        if len(matches)!=1: raise ReviewRequired('DERIVATIVE_DOES_NOT_COVER_EXACT_CLIP')
        d=matches[0]; origin=d['source_range_frames'][0]
        frame=definition.find('media/video/samplecharacteristics')
        if frame is None: raise ReviewRequired('ORIGINAL_VIDEO_GEOMETRY_MISSING')
        if integer(frame,'width')!=d.get('width') or integer(frame,'height')!=d.get('height'):
            raise ReviewRequired('DERIVATIVE_GEOMETRY_MISMATCH')
        replacement=copy.deepcopy(definition)
        replacement.set('id','rg-smoking-'+d['sha256'][:32]+'-'+str(origin))
        for name,value in (('name',Path(d['path']).name),('pathurl',Path(d['path']).resolve().as_uri()),('duration',str(d['frames']))):
            node=replacement.find(name)
            if node is None: node=ET.SubElement(replacement,name)
            node.text=value
        for audio in replacement.findall('./media/audio'):
            replacement.find('media').remove(audio)
        position=list(clip).index(file); clip.remove(file); clip.insert(position,replacement)
        clip.find('in').text=str(inside-origin); clip.find('out').text=str(outside-origin)
        for field,number in (('pproTicksIn',inside-origin),('pproTicksOut',outside-origin)):
            tick=clip.find(field)
            if tick is not None: tick.text=str(number*TICKS_PER_SECOND//30)
        count+=1; used.add(path_identity(d['path']))
    if count==0 or used!=set(identities): raise ReviewRequired('UNUSED_OR_UNMAPPED_DERIVATIVE')
    # Keep the original media definition reachable by audio even if the first
    # video clip used to be its sole definition. Audio still reads original media.
    for file in root.findall('./sequence/media/audio//file'):
        definition=definitions.get(file.get('id'))
        if not file.findtext('pathurl') and definition is not None:
            for child in list(file): file.remove(child)
            for child in definition: file.append(copy.deepcopy(child))
    if resolved_audio_hash(root)!=original_audio:
        raise ReviewRequired('AUDIO_TIMELINE_OR_MEDIA_CHANGED')
    return b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'+ET.tostring(root,encoding='utf-8')


def write_candidate(original_path,derivatives,output,dialogue):
    original_path=Path(original_path); output=Path(output)
    if not output.name.endswith('.candidate.xml'):
        raise ReviewRequired('ONLY_CANDIDATE_XML_OUTPUT_ALLOWED')
    if output.exists() or output.resolve()==original_path.resolve():
        raise ReviewRequired('REFUSE_OVERWRITING_XML')
    before=sha256_file(original_path)
    for item in derivatives:
        if sha256_file(item['path'])!=item.get('sha256'):
            raise ReviewRequired('DERIVATIVE_CONTENT_CHANGED')
    data=candidate_bytes(original_path.read_bytes(),derivatives,dialogue)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('xb') as f: f.write(data)
    if sha256_file(original_path)!=before:
        raise ReviewRequired('ORIGINAL_XML_CHANGED')
    return dict(candidate_xml_sha256=sha256_file(output),original_xml_sha256=before,
        resolved_audio_sha256=resolved_audio_hash(data),production_release_allowed=False)
