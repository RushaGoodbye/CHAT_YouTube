"""Lossless video-only candidates. Decode and verify every encoded frame."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from rg_smoking_compliance import (LAYERS,VERSION,MaskPolicy,ReviewRequired,
    blur_frame,compose_masks,sha256_file)


def executable(name):
    candidates=[shutil.which(name),str(Path(r'C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin')/(name+'.exe'))]
    for path in candidates:
        if path and Path(path).is_file(): return path
    raise ReviewRequired('MEDIA_EXECUTABLE_MISSING:'+name)


def probe_video_only(path):
    result=subprocess.run([executable('ffprobe'),'-v','error','-show_streams','-of','json',str(path)],
        capture_output=True,text=True,encoding='utf-8',timeout=30)
    if result.returncode: raise ReviewRequired('DERIVATIVE_FFPROBE_FAILED')
    streams=json.loads(result.stdout).get('streams',[])
    if len(streams)!=1 or streams[0].get('codec_type')!='video':
        raise ReviewRequired('DERIVATIVE_MUST_HAVE_EXACTLY_ONE_VIDEO_NO_AUDIO')
    if streams[0].get('codec_name')!='qtrle' or streams[0].get('avg_frame_rate')!='30/1':
        raise ReviewRequired('LOSSLESS_CFR_QTRLE_CANDIDATE_REQUIRED')
    return streams[0]


def unpack_layers(packed,i,width):
    import numpy as np
    return {k:np.unpackbits(packed[k][i],axis=1,count=width).astype(bool) for k in LAYERS}


def expected_frame(image,row,scan,packed,index):
    if hashlib.sha256(image.tobytes()).hexdigest()!=row['decoded_frame_sha256']:
        raise ReviewRequired('DECODED_SOURCE_FRAME_IDENTITY_MISMATCH')
    if row['state']=='VERIFIED_NEGATIVE': return image
    if row['state']!='CONFIRMED_SMOKING': raise ReviewRequired('CANNOT_RENDER_UNKNOWN_SMOKING_STATE')
    layers=unpack_layers(packed,index,image.shape[1])
    alpha,_=compose_masks(layers,row['required'],image.shape[:2],
        row.get('roi_xyxy',scan.get('roi_xyxy')),policy=MaskPolicy(**scan['mask_policy']))
    return blur_frame(image,alpha,MaskPolicy(**scan['mask_policy']))


def validate_decoded_source_and_derivatives(source,scan,packed,derivatives):
    import cv2
    import numpy as np
    cap=cv2.VideoCapture(str(source)); outputs={}; decoded=0
    if not cap.isOpened() or abs(cap.get(cv2.CAP_PROP_FPS)-30)>.001:
        raise ReviewRequired('ORIGINAL_CFR_30_SOURCE_REQUIRED')
    try:
        for d in derivatives:
            stream=probe_video_only(d['path'])
            if int(stream.get('width',0))!=d['width'] or int(stream.get('height',0))!=d['height']:
                raise ReviewRequired('ENCODED_DERIVATIVE_GEOMETRY_MISMATCH')
            output=cv2.VideoCapture(d['path'])
            if not output.isOpened() or int(output.get(cv2.CAP_PROP_FRAME_COUNT))!=d['frames']:
                raise ReviewRequired('ENCODED_DERIVATIVE_FRAME_COUNT_MISMATCH')
            outputs[d['path']]=output
        last=None
        for index,row in enumerate(scan['frames']):
            number=row['source_frame']
            if last is None or number!=last+1:
                if not cap.set(cv2.CAP_PROP_POS_FRAMES,number): raise ReviewRequired('SOURCE_SEEK_FAILED')
            ok,image=cap.read(); last=number
            if not ok or list(image.shape[:2])!=scan['source_shape_hw']:
                raise ReviewRequired('SOURCE_FRAME_MISSING_OR_GEOMETRY_CHANGED')
            if abs(cap.get(cv2.CAP_PROP_POS_FRAMES)-(number+1))>.01:
                raise ReviewRequired('SOURCE_DECODER_FRAME_INDEX_MISMATCH')
            expected=expected_frame(image,row,scan,packed,index)
            active=[d for d in derivatives if d['source_range_frames'][0]<=number<d['source_range_frames'][1]]
            if len(active)>1 or (row['state']=='CONFIRMED_SMOKING' and len(active)!=1):
                raise ReviewRequired('RENDERED_SMOKING_FRAME_COVERAGE_INVALID')
            if active:
                d=active[0]; output=outputs[d['path']]
                if abs(output.get(cv2.CAP_PROP_POS_FRAMES)-(number-d['source_range_frames'][0]))>.01:
                    raise ReviewRequired('DERIVATIVE_FRAME_ORDER_OR_SCOPE_MISMATCH')
                ok,actual=output.read()
                if not ok or actual.shape!=expected.shape or not np.array_equal(actual,expected):
                    raise ReviewRequired('ENCODED_FRAME_DIFFERS_FROM_VERIFIED_FOUR_LAYER_RENDER')
            decoded+=1
        for d in derivatives:
            output=outputs[d['path']]
            if output.get(cv2.CAP_PROP_POS_FRAMES)!=d['frames'] or output.read()[0]:
                raise ReviewRequired('DERIVATIVE_HAS_UNREVIEWED_OR_EXTRA_FRAMES')
    finally:
        cap.release()
        for output in outputs.values(): output.release()
    return decoded


def render_candidate(source,scan,mask_archive,output,source_range):
    import cv2
    import numpy as np
    from rg_smoking_studio_gate import verify_masks
    source=Path(source); output=Path(output)
    if not output.name.endswith('.candidate.mov') or output.exists() or output.resolve()==source.resolve():
        raise ReviewRequired('ONLY_NEW_CANDIDATE_MOV_OUTPUT_ALLOWED')
    if sha256_file(source)!=scan['source_sha256']: raise ReviewRequired('SOURCE_IDENTITY_MISMATCH')
    if scan.get('version')!=VERSION: raise ReviewRequired('RENDER_SCHEMA_VERSION_MISMATCH')
    verify_masks(scan,mask_archive)
    with np.load(mask_archive,allow_pickle=False) as z: packed={k:z[k] for k in LAYERS}
    a,b=source_range; h,w=scan['source_shape_hw']
    indices=[i for i,row in enumerate(scan['frames']) if a<=row['source_frame']<b]
    if [scan['frames'][i]['source_frame'] for i in indices]!=list(range(a,b)):
        raise ReviewRequired('RENDER_SOURCE_FRAME_SCOPE_INCOMPLETE')
    output.parent.mkdir(parents=True,exist_ok=True)
    log_path=output.with_suffix('.ffmpeg.log')
    cap=cv2.VideoCapture(str(source)); cap.set(cv2.CAP_PROP_POS_FRAMES,a)
    try:
        with log_path.open('wb') as log:
            process=subprocess.Popen([executable('ffmpeg'),'-v','error','-nostdin','-n',
                '-f','rawvideo','-pix_fmt','bgr24','-s','%dx%d'%(w,h),'-framerate','30','-i','pipe:0',
                '-an','-c:v','qtrle','-pix_fmt','rgb24','-threads','4',str(output)],
                stdin=subprocess.PIPE,stderr=log,stdout=subprocess.DEVNULL)
            try:
                for i in indices:
                    ok,image=cap.read()
                    if not ok: raise ReviewRequired('RENDER_SOURCE_DECODE_FAILED')
                    result=expected_frame(image,scan['frames'][i],scan,packed,i)
                    process.stdin.write(result.tobytes())
                process.stdin.close()
                if process.wait(timeout=120): raise ReviewRequired('LOSSLESS_CANDIDATE_ENCODER_FAILED')
            finally:
                if process.poll() is None: process.kill(); process.wait()
    finally: cap.release()
    derivative=dict(source_path=str(source),source_range_frames=[a,b],path=str(output),
        sha256=sha256_file(output),frames=b-a,width=w,height=h,fps_numerator=30,
        fps_denominator=1,has_audio=False,renderer_version=VERSION)
    subset=dict(scan,frames=[scan['frames'][i] for i in indices])
    reduced={k:packed[k][indices] for k in LAYERS}
    validate_decoded_source_and_derivatives(source,subset,reduced,[derivative])
    if sha256_file(source)!=scan['source_sha256']: raise ReviewRequired('SOURCE_CHANGED_DURING_RENDER')
    return derivative
