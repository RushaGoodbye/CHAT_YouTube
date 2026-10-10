"""Physical evidence gate for Studio. Legacy `passed: true` is insufficient."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from rg_smoking_compliance import (LAYERS,VERSION,ReviewRequired,MaskPolicy,
    compose_masks,evaluate_scan,sha256_file,valid_sha)
from rg_smoking_timeline import file_definitions,path_identity,source_scope
from rg_smoking_xml import candidate_bytes,local_path,resolved_audio_hash
from rg_smoking_media import validate_decoded_source_and_derivatives

SCHEMA='RG_SMOKING_COMPLIANCE_DELIVERY_V1'


def read_bound_json(path,expected):
    if not valid_sha(expected) or sha256_file(path)!=expected:
        raise ReviewRequired('EVIDENCE_FILE_CONTENT_CHANGED')
    value=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value,dict): raise ReviewRequired('EVIDENCE_JSON_INVALID')
    return value


def verify_masks(scan,path):
    import numpy as np
    shape=scan.get('source_shape_hw')
    if not isinstance(shape,list) or len(shape)!=2 or any(type(v) is not int or v<1 or v>4096 for v in shape):
        raise ReviewRequired('LOSSLESS_MASK_FRAME_SHAPE_MISSING')
    h,w=shape
    rows=scan['frames']; total=len(rows)
    with np.load(path,allow_pickle=False) as archive:
        if set(archive.files)!=set(LAYERS): raise ReviewRequired('LOSSLESS_FOUR_LAYERS_REQUIRED')
        packed={k:archive[k] for k in LAYERS}
    if any(v.dtype!=np.uint8 or v.shape!=(total,h,(w+7)//8) for v in packed.values()):
        raise ReviewRequired('LOSSLESS_MASK_ARCHIVE_SHAPE_INVALID')
    try: policy=MaskPolicy(**scan['mask_policy'])
    except (KeyError,TypeError,ValueError): raise ReviewRequired('VERIFIED_MASK_POLICY_MISSING')
    for i,row in enumerate(rows):
        layers={k:np.unpackbits(packed[k][i],axis=1,count=w).astype(bool) for k in LAYERS}
        if row['state']=='VERIFIED_NEGATIVE':
            if any(v.any() for v in layers.values()): raise ReviewRequired('NEGATIVE_HAS_PHYSICAL_MASK')
            continue
        digest=hashlib.sha256(b''.join(layers[k].tobytes() for k in LAYERS)).hexdigest()
        if digest!=row['mask_sha256']: raise ReviewRequired('PHYSICAL_MASK_IDENTITY_MISMATCH')
        if any(int(layers[k].sum())!=row['layer_pixels'][k] for k in LAYERS):
            raise ReviewRequired('PHYSICAL_MASK_PIXEL_COUNTS_MISMATCH')
        compose_masks(layers,row['required'],tuple(shape),row.get('roi_xyxy',scan.get('roi_xyxy')),policy=policy)
    return total


def original_video_sources(original):
    root=ET.fromstring(original); definitions=file_definitions(root); sources={}
    for clip in root.findall('./sequence/media/video/track/clipitem'):
        file=clip.find('file')
        if file is None: raise ReviewRequired('UNRESOLVED_ORIGINAL_VIDEO')
        definition=definitions.get(file.get('id'),file)
        raw=definition.findtext('pathurl')
        if not raw: raise ReviewRequired('UNRESOLVED_ORIGINAL_VIDEO')
        path=local_path(raw)
        # Static graphics have no time-dependent smoking states. Moving media,
        # including backgrounds, require complete evidence; no filename skip.
        if path.suffix.lower() in ('.png','.jpg','.jpeg','.bmp','.tif','.tiff'): continue
        sources[path_identity(path)]=path
    if not sources: raise ReviewRequired('ORIGINAL_VIDEO_SOURCES_MISSING')
    return sources


def evaluate_for_xml(xml_path):
    xml_path=Path(xml_path); failures=[]; checked=[]
    try:
        match=re.fullmatch(r'RG_EDITED_(\d+_\d+)(?:\.candidate)?',xml_path.stem)
        if match and match.group(1)=='886_5':
            raise ReviewRequired('886_5_QUARANTINED_NO_EXPORT')
        for hold in (xml_path.with_suffix('.SEMANTIC_HOLD.json'),
                     xml_path.with_name(xml_path.stem.replace('.candidate','')+'.SEMANTIC_HOLD.json')):
            if hold.exists(): raise ReviewRequired('SEMANTIC_HOLD_NO_EXPORT')
        sidecar=xml_path.with_name(xml_path.stem+'_SMOKING_COMPLIANCE_QA.json')
        if not sidecar.is_file(): raise ReviewRequired('FOUR_LAYER_SMOKING_QA_MISSING')
        delivery=json.loads(sidecar.read_text(encoding='utf-8-sig'))
        if delivery.get('schema')!=SCHEMA or delivery.get('version')!=VERSION:
            raise ReviewRequired('FOUR_LAYER_DELIVERY_SCHEMA_INVALID')
        if not match or delivery.get('dialogue')!=match.group(1):
            raise ReviewRequired('DELIVERY_DIALOGUE_MISMATCH')
        dialogue=delivery['dialogue']
        if sha256_file(xml_path)!=delivery.get('candidate_xml_sha256'):
            raise ReviewRequired('CANDIDATE_XML_CONTENT_CHANGED')
        original_path=Path(delivery['original_xml_path'])
        if sha256_file(original_path)!=delivery.get('original_xml_sha256'):
            raise ReviewRequired('ORIGINAL_XML_CONTENT_CHANGED')
        original=original_path.read_bytes(); candidate=xml_path.read_bytes()
        if resolved_audio_hash(candidate)!=resolved_audio_hash(original):
            raise ReviewRequired('AUDIO_TIMELINE_OR_MEDIA_CHANGED')
        sources=original_video_sources(original)
        entries=delivery.get('source_entries')
        if not isinstance(entries,list) or not entries: raise ReviewRequired('SOURCE_EVIDENCE_MISSING')
        seen=set(); smoking_sources=set(); validated={}
        for entry in entries:
            identity=path_identity(entry['source_path'])
            if identity not in sources or identity in seen: raise ReviewRequired('UNEXPECTED_OR_DUPLICATE_SOURCE_EVIDENCE')
            seen.add(identity)
            source=sources[identity]
            if sha256_file(source)!=entry['source_sha256']: raise ReviewRequired('SOURCE_MEDIA_CONTENT_CHANGED')
            scope=source_scope(original,source)
            scan=read_bound_json(entry['scan_path'],entry['scan_file_sha256'])
            review=read_bound_json(entry['independent_review_path'],entry['review_file_sha256'])
            gate=evaluate_scan(scan,source_sha256=entry['source_sha256'],ranges=scope['ranges'],
                dialogue=dialogue,independent_review=review)
            if not gate['release_allowed']:
                failures.extend(gate['failures']); continue
            if sha256_file(entry['mask_archive_path'])!=entry['mask_archive_sha256']:
                raise ReviewRequired('LOSSLESS_MASK_ARCHIVE_CONTENT_CHANGED')
            frames=verify_masks(scan,entry['mask_archive_path'])
            import numpy as np
            with np.load(entry['mask_archive_path'],allow_pickle=False) as archive:
                packed={k:archive[k] for k in LAYERS}
            validated[identity]=(scan,packed)
            if any(r['state']=='CONFIRMED_SMOKING' for r in scan['frames']): smoking_sources.add(identity)
            checked.append(dict(source_sha256=entry['source_sha256'],reviewed_frames=frames))
        if seen!=set(sources): raise ReviewRequired('UNREVIEWED_MOVING_MEDIA_SOURCE')
        derivatives=delivery.get('derivatives',[])
        rendered_sources=set()
        for d in derivatives:
            identity=path_identity(d['source_path'])
            if identity not in smoking_sources: raise ReviewRequired('UNVERIFIED_OR_UNNECESSARY_VIDEO_DERIVATIVE')
            if sha256_file(d['path'])!=d['sha256']: raise ReviewRequired('RENDERED_MEDIA_CONTENT_CHANGED')
            rendered_sources.add(identity)
        if rendered_sources!=smoking_sources: raise ReviewRequired('SMOKING_SOURCE_NOT_REDACTED')
        for identity,(scan,packed) in validated.items():
            validate_decoded_source_and_derivatives(sources[identity],scan,packed,
                [d for d in derivatives if path_identity(d['source_path'])==identity])
        if candidate_bytes(original,derivatives,dialogue)!=candidate:
            raise ReviewRequired('CANDIDATE_TIMELINE_DIFFERS_FROM_VERIFIED_REWRITE')
    except Exception as exc:
        failures.append(str(exc) if isinstance(exc,ReviewRequired) else 'SMOKING_EVIDENCE_INVALID:'+type(exc).__name__)
    failures=list(dict.fromkeys(failures))
    return dict(version=VERSION,passed=not failures,release_allowed=not failures,
        status='READY_AFTER_REVIEW' if not failures else 'REVIEW_REQUIRED',
        failures=failures,checked_sources=checked)
