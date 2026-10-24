"""Read every retained source frame. Zero YOLO hits never certify a negative.

Reuses the installed detector's isolated worker packages, without installing or
changing them. All predictions remain proposals and require semantic review.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback
from rg_smoking_compliance import ReviewRequired, sha256_file
from rg_smoking_timeline import source_scope
from run_real_four_layer_qa import APP, ROOT, SOURCE, SOURCE_SHA, HOLD, protected

NEGATIVE=Path(r'\\Desktop-v7gg0en\record\886.mp4')
DATA=ROOT.parent


def stat_identity(path):
    s=path.stat(); return dict(bytes=s.st_size,mtime_ns=s.st_mtime_ns)


def source_hash(path):
    h=hashlib.sha256(); size=0; mark=0
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024**2),b''):
            h.update(chunk); size+=len(chunk)
            if size-mark>=1024**3:
                mark=size; print('RG_SOURCE_HASH|%s|GiB=%.1f'%(path.name,size/1024**3),flush=True)
    return h.hexdigest()


def scan_source(model,path,ranges,output,name,source_sha):
    import cv2
    import numpy as np
    cap=cv2.VideoCapture(str(path))
    if not cap.isOpened() or abs(cap.get(cv2.CAP_PROP_FPS)-30)>.001:
        raise ReviewRequired('CFR_30_SOURCE_REQUIRED')
    frame_count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    shape=(int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)))
    if max(shape)>4096 or min(shape)<720: raise ReviewRequired('SOURCE_SHAPE_UNSUPPORTED')
    wanted=sum(b-a for a,b in ranges)
    if any(b>frame_count for a,b in ranges): raise ReviewRequired('SOURCE_SCOPE_OUT_OF_BOUNDS')
    rows=[]; contacts=[]; detection_frames=0; total_boxes=0; known_mic_hit_frames=0
    start_time=time.monotonic()
    snippets=cv2.VideoWriter(str(output/(name+'_known_fixture.mp4')),
        cv2.VideoWriter_fourcc(*'mp4v'),30,(shape[1],shape[0]))
    if not snippets.isOpened(): raise ReviewRequired('FIXTURE_VIDEO_WRITER_FAILED')
    try:
        with gzip.open(output/(name+'_dense_frames.jsonl.gz'),'wt',encoding='utf-8') as f:
            for a,b in ranges:
                if not cap.set(cv2.CAP_PROP_POS_FRAMES,a): raise ReviewRequired('SOURCE_SEEK_FAILED')
                batch=[]; numbers=[]
                for index in range(a,b):
                    ok,frame=cap.read()
                    if not ok or frame.shape[:2]!=shape:
                        raise ReviewRequired('SOURCE_FRAME_DECODE_MISSING:'+str(index))
                    if abs(cap.get(cv2.CAP_PROP_POS_FRAMES)-(index+1))>.01:
                        raise ReviewRequired('SOURCE_DECODER_FRAME_INDEX_MISMATCH')
                    batch.append(frame); numbers.append(index)
                    if len(batch)<4 and index!=b-1: continue
                    predictions=model.predict(source=batch,conf=.08,iou=.5,imgsz=1280,
                        device=0,verbose=False,max_det=100)
                    if len(predictions)!=len(batch): raise ReviewRequired('PREDICTION_FRAME_DROPPED')
                    for image,number,pred in zip(batch,numbers,predictions):
                        boxes=[]
                        for box in pred.boxes:
                            xy=box.xyxy[0].detach().cpu().tolist()
                            boxes.append(dict(bbox=[round(float(v),3) for v in xy],
                                score=float(box.conf[0].detach().cpu()),
                                label=str(pred.names[int(box.cls[0].detach().cpu())])))
                        mic_fixture=name=='886_5' and 9558.9<=number/30<9561.2
                        if boxes:
                            detection_frames+=1; total_boxes+=len(boxes)
                            if mic_fixture: known_mic_hit_frames+=1
                        row=dict(source_frame=number,decoded_frame_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
                            boxes=boxes,state='MODEL_PROPOSAL_REQUIRES_REVIEW' if boxes else 'UNVERIFIED_NO_DETECTIONS',
                            mask_pixels=0,release_allowed=False)
                        f.write(json.dumps(row,separators=(',',':'))+'\n')
                        rows.append(number)
                        selected=(name=='892' and number in (0,60,120,180,240,300,360,390,419,480,540,600,660,719)) or (
                            name=='886_5' and (number-a)%900==0)
                        if selected or mic_fixture or (name=='892' and 360<=number<420):
                            view=image.copy()
                            for bx in boxes:
                                x0,y0,x1,y1=[int(v) for v in bx['bbox']]
                                cv2.rectangle(view,(x0,y0),(x1,y1),(0,0,255),2)
                            if selected:
                                tile=cv2.resize(view,(640,360))
                                cv2.putText(tile,'%s frame %d proposals %d'%(name,number,len(boxes)),
                                    (8,25),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,255),2)
                                contacts.append(tile)
                                cv2.imwrite(str(output/('%s_frame_%d.png'%(name,number))),view)
                            if mic_fixture or (name=='892' and 360<=number<420): snippets.write(view)
                    if len(rows)%300<4:
                        print('RG_DENSE_QA|%s|decoded=%d/%d|hit_frames=%d|elapsed=%.1f'%(
                            name,len(rows),wanted,detection_frames,time.monotonic()-start_time),flush=True)
                    batch=[]; numbers=[]
        expected=[n for a,b in ranges for n in range(a,b)]
        if rows!=expected: raise ReviewRequired('FULL_SOURCE_FRAME_COVERAGE_FAILED')
        for offset in range(0,len(contacts),9):
            cells=contacts[offset:offset+9]
            cells+=[np.zeros((360,640,3),np.uint8)]*(9-len(cells))
            sheet=np.concatenate([np.concatenate(cells[j:j+3],axis=1) for j in (0,3,6)],axis=0)
            cv2.imwrite(str(output/('%s_sheet_%02d.jpg'%(name,offset//9))),sheet)
    finally:
        cap.release(); snippets.release()
    return dict(source_sha256=source_sha,source_ranges_frames=ranges,source_shape_hw=list(shape),
        source_frame_count=frame_count,expected_frames=wanted,decoded_frames=len(rows),
        all_source_frames_decoded=True,frames_with_model_proposals=detection_frames,
        raw_model_boxes=total_boxes,known_microphone_fixture_proposal_frames=known_mic_hit_frames,
        masks_applied=0,zero_detections_certify_negative=False,semantic_accuracy_measured=False,
        frame_evidence_sha256=sha256_file(output/(name+'_dense_frames.jsonl.gz')),
        seconds=round(time.monotonic()-start_time,2),release_allowed=False)


def run(output):
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    before=protected()
    report=dict(schema='RG_SMOKING_FULL_SOURCE_EVIDENCE_V1',release_allowed=False,
        status='RUNNING',results={},studio_changed=False)
    initial={}
    try:
        sys.path.insert(0,str(Path(__file__).parents[1]/'open_source_v1'))
        from audit_886_5_dialogue_preflight_v1 import verify_quarantine
        hold,clean,fixture=verify_quarantine()
        # Reading every referenced source frame is valid even when a clip has
        # non-unit speed. This does not certify source-to-output mask mapping.
        scope=source_scope(clean.read_bytes(),NEGATIVE,allow_timewarp_for_source_audit=True)
        report['withheld_xml_sha256']=sha256_file(clean)
        report['negative_scope']=scope
        if sha256_file(SOURCE)!=SOURCE_SHA: raise ReviewRequired('PINNED_POSITIVE_SOURCE_CHANGED')
        import torch
        from ultralytics import YOLOWorld
        if not torch.cuda.is_available(): raise ReviewRequired('CUDA_DETECTOR_UNAVAILABLE')
        manifest=json.loads((DATA/'cigarette_detector_v1.json').read_text(encoding='utf-8-sig'))
        model_path=Path(manifest.get('model') or DATA/'models/cigarette_blur/yolov8s-worldv2.pt')
        model_sha=sha256_file(model_path)
        report['model_sha256']=model_sha; report['torch_version']=torch.__version__
        report['gpu']=torch.cuda.get_device_name(0)
        for p in (SOURCE,NEGATIVE): initial[str(p)]=stat_identity(p)
        neg_sha=source_hash(NEGATIVE)
        model=YOLOWorld(str(model_path))
        model.set_classes(['cigarette','lit cigarette','cigarette in hand','smoking cigarette'])
        report['results']['892']=scan_source(model,SOURCE,[[0,720]],output,'892',SOURCE_SHA)
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        report['results']['886_5']=scan_source(model,NEGATIVE,scope['ranges'],output,'886_5',neg_sha)
        if source_hash(NEGATIVE)!=neg_sha or sha256_file(SOURCE)!=SOURCE_SHA:
            raise ReviewRequired('SOURCE_MEDIA_CHANGED')
        if sha256_file(model_path)!=model_sha: raise ReviewRequired('DETECTOR_MODEL_CHANGED')
        report['status']='ALL_RETAINED_SOURCE_FRAMES_SCANNED_SEMANTIC_REVIEW_REQUIRED'
        report['source_media_changed']=any(stat_identity(Path(p))!=v for p,v in initial.items())
        if report['source_media_changed']: raise ReviewRequired('SOURCE_MEDIA_STAT_CHANGED')
    except Exception as exc:
        report['status']='FAILED_RELEASE_BLOCKED'; report['error']=str(exc)
        (output/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
    finally:
        report['studio_changed']=protected()!=before
        report['quarantine_886_5_unchanged']=before.get(str(HOLD))==sha256_file(HOLD)
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('RG_DENSE_QA_RESULT|'+json.dumps(report['results']),flush=True)
        if report['studio_changed']: raise ReviewRequired('PROTECTED_STUDIO_CHANGED')


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--output',required=True)
    run(p.parse_args().output)
