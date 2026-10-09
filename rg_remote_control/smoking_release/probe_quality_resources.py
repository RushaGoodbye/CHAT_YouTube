"""Locate actual annotation data and check public model access without tokens.

No account creation, authentication, contact sharing or license acceptance.
Capture the eight real failure references using their recorded pixel hashes.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import traceback
from rg_smoking_compliance import ReviewRequired,sha256_file
from run_real_four_layer_qa import APP,ROOT,HOLD,protected

DATA=ROOT.parent
PRIOR=ROOT/'smoking_full_evidence_v1/f430053c16a4488ebe8904c99deeb04c6e11c3b6/dense-source'
NEGATIVE=Path(r'\\Desktop-v7gg0en\record\886.mp4')
NAS=Path(r'\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC')


def bounded_files(root,depth=6):
    if not root.is_dir(): return
    for folder,subdirs,files in os.walk(root):
        relative=Path(folder).relative_to(root)
        subdirs[:]=[s for s in subdirs if s not in ('site-packages','oss_envs','.git','__pycache__')]
        if len(relative.parts)>=depth: subdirs[:]=[]
        for name in files: yield Path(folder)/name


def run(output):
    import cv2
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    before=protected()
    report=dict(schema='RG_SMOKING_QUALITY_RESOURCE_PREFLIGHT_V1',release_allowed=False,
        model_access={},cached_sam3=[],annotation_candidates=[],failure_references=[])
    try:
        # Metadata only. Explicit token=False prevents reading/sending an
        # existing account token. New legal conditions require the account owner.
        try:
            from huggingface_hub import get_hf_file_metadata,hf_hub_url
            meta=get_hf_file_metadata(hf_hub_url('facebook/sam3','sam3.pt'),token=False,timeout=15)
            report['model_access']=dict(status='PUBLIC_ACCESS_AVAILABLE',commit=meta.commit_hash,
                bytes=meta.size,model='facebook/sam3',checkpoint='sam3.pt',weights_downloaded=False)
        except Exception as exc:
            status=getattr(getattr(exc,'response',None),'status_code',None)
            report['model_access']=dict(status='AUTHENTICATION_OR_ACCESS_REQUIRED' if status in (401,403)
                else 'MODEL_METADATA_UNAVAILABLE',http_status=status,error_type=type(exc).__name__,
                model='facebook/sam3',weights_downloaded=False,account_token_used=False)
        for base in (ROOT,DATA/'models',DATA/'datasets',DATA/'annotations',DATA/'smoking_compliance',NAS):
            for p in bounded_files(base):
                if p.name in ('sam3.pt','sam3.1_multiplex.pt') or (
                        p.suffix=='.safetensors' and 'sam3' in str(p.relative_to(base)).casefold()):
                    report['cached_sam3'].append(dict(path=str(p),bytes=p.stat().st_size,sha256=sha256_file(p)))
                low=p.name.lower()
                if p.suffix.lower()!='.json' or not any(k in low for k in ('annotat','human','ground_truth','labels','_gt.')):
                    continue
                if p.stat().st_size>16*1024**2: continue
                try: value=json.loads(p.read_text(encoding='utf-8-sig'))
                except (ValueError,UnicodeError): continue
                if not isinstance(value,dict): continue
                hints={k:value[k] for k in ('schema','ground_truth_verified','manual_ground_truth_pixels',
                    'human_verified','annotator_type','ground_truth_labelled') if k in value}
                # Do not certify labels just because a manifest says "human".
                if hints:
                    report['annotation_candidates'].append(dict(path=str(p),sha256=sha256_file(p),
                        declared=hints,independent_provenance_verified=False))
        prior=json.loads((PRIOR/'report.json').read_text(encoding='utf-8'))
        evidence=PRIOR/'886_5_dense_frames.jsonl.gz'
        if sha256_file(evidence)!=prior['results']['886_5']['frame_evidence_sha256']:
            raise ReviewRequired('FULL_SOURCE_FAILURE_EVIDENCE_CHANGED')
        with gzip.open(evidence,'rt',encoding='utf-8') as f:
            targets=[json.loads(line) for line in f if 'MODEL_PROPOSAL_REQUIRES_REVIEW' in line]
        if len(targets)!=8: raise ReviewRequired('EXPECTED_EIGHT_FAILURE_REFERENCES_CHANGED')
        cap=cv2.VideoCapture(str(NEGATIVE))
        try:
            for row in targets:
                number=row['source_frame'];cap.set(cv2.CAP_PROP_POS_FRAMES,number)
                ok,image=cap.read()
                if not ok or hashlib.sha256(image.tobytes()).hexdigest()!=row['decoded_frame_sha256']:
                    raise ReviewRequired('FAILURE_REFERENCE_SOURCE_PIXELS_CHANGED')
                box=row['boxes'][0]['bbox'];x0,y0,x1,y1=[int(v) for v in box]
                crop=image[max(0,y0-100):min(1080,y1+100),max(0,x0-100):min(1920,x1+100)]
                name='failure_frame_%d'%number
                cv2.imwrite(str(output/(name+'_original.png')),image)
                cv2.imwrite(str(output/(name+'_crop.png')),crop)
                view=image.copy();cv2.rectangle(view,(x0,y0),(x1,y1),(0,0,255),2)
                cv2.imwrite(str(output/(name+'_proposal.png')),view)
                report['failure_references'].append(dict(source_frame=number,
                    decoded_frame_sha256=row['decoded_frame_sha256'],bbox=box,
                    human_pixel_labels_created=False,release_allowed=False,
                    known_fixture_window=9558.9<=number/30<9561.2))
        finally:cap.release()
        report['status']='RESOURCE_CHECK_COMPLETED_NO_RELEASE'
    except Exception as exc:
        report['status']='RESOURCE_CHECK_FAILED_NO_RELEASE';report['error']=str(exc)
        (output/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
    finally:
        report['studio_changed']=before!=protected()
        report['quarantine_886_5_unchanged']=before.get(str(HOLD))==sha256_file(HOLD)
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('RG_QUALITY_RESOURCES|'+json.dumps({k:report[k] for k in ('model_access','cached_sam3',
            'annotation_candidates','studio_changed','quarantine_886_5_unchanged')}),flush=True)
        if report['studio_changed']:raise ReviewRequired('PROTECTED_STUDIO_CHANGED')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    run(p.parse_args().output)
