"""Test real smoke segmentation, without silently approving a fallback box."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import traceback

from run_real_four_layer_qa import (CONFIG, MODEL, SOURCE, SOURCE_SHA, COUNT,
    START, preflight, protected, extract_frames)
from rg_smoking_compliance import sha256_file, ReviewRequired


def run(output):
    import cv2
    import numpy as np
    import torch
    from hydra import initialize_config_dir
    from hydra.core.global_hydra import GlobalHydra
    from sam2.build_sam import build_sam2_video_predictor
    preflight()
    before = protected()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    report = dict(schema='RG_SMOKE_SEGMENTATION_PROBE_V1', source_sha256=SOURCE_SHA,
        frames=COUNT, source_start_frame=START, release_allowed=False,
        semantic_ground_truth_available=False, methods=[])
    try:
        folder = extract_frames(output)
        GlobalHydra.instance().clear()
        initialize_config_dir(version_base='1.2', config_dir=str(CONFIG.resolve(strict=True)))
        with torch.inference_mode():
            predictor = build_sam2_video_predictor('sam2.1/sam2.1_hiera_t.yaml',
                str(MODEL), device='cuda', apply_postprocessing=False)
            cases = {
                'smoke_points_forward': (0, False,
                    [(1230,338,1),(1259,285,1),(1261,232,1),(1283,195,1),
                     (1273,164,1),(1299,124,1),(1308,100,1),
                     (1140,210,0),(1392,274,0),(1230,460,0),(1500,400,0)]),
                'smoke_points_reverse': (59, True,
                    [(1250,197,1),(1281,257,1),(1328,185,1),(1364,130,1),
                     (1396,153,1),(1356,252,1),(1414,213,1),
                     (1190,170,0),(1230,420,0),(1480,391,0),(1520,142,0)])}
            cap = cv2.VideoCapture(str(SOURCE))
            try:
                for name,(first,reverse,seed) in cases.items():
                    state = predictor.init_state(str(folder),offload_video_to_cpu=True,
                        offload_state_to_cpu=True,async_loading_frames=False)
                    predictor.add_new_points_or_box(state,frame_idx=first,obj_id=1,
                        points=np.asarray([p[:2] for p in seed],np.float32),
                        labels=np.asarray([p[2] for p in seed],np.int32))
                    masks = {}
                    for index,ids,logits in predictor.propagate_in_video(state,
                            start_frame_idx=first,max_frame_num_to_track=COUNT-1,reverse=reverse):
                        mask=(logits[list(ids).index(1)]>0).detach().cpu().numpy().squeeze()
                        if mask.shape!=(1080,1920) or int(index) in masks:
                            raise ReviewRequired('SMOKE_TRACK_FORMAT_INVALID')
                        masks[int(index)]=mask.astype(bool)
                    if set(masks)!=set(range(COUNT)):
                        raise ReviewRequired('SMOKE_TRACK_INCOMPLETE')
                    np.savez_compressed(output/(name+'.npz'),smoke=np.asarray(
                        [np.packbits(masks[i],axis=1) for i in range(COUNT)]))
                    areas=[int(masks[i].sum()) for i in range(COUNT)]
                    report['methods'].append(dict(name=name,seed_frame=START+first,
                        seeds=seed,empty_frames=sum(a==0 for a in areas),
                        excessive_area_frames=sum(a>1080*1920*.12 for a in areas),
                        pixels=areas,semantic_approved=False,
                        masks_sha256=sha256_file(output/(name+'.npz'))))
                    for i in (0,20,40,59):
                        cap.set(cv2.CAP_PROP_POS_FRAMES,START+i)
                        ok,im=cap.read()
                        if not ok: raise ReviewRequired('SMOKE_REVIEW_FRAME_MISSING')
                        color=im.copy()
                        color[masks[i]]=(color[masks[i]]*.45+np.array([0,210,255])*.55).astype(np.uint8)
                        side=np.concatenate([im[65:775,1020:1660],color[65:775,1020:1660]],axis=1)
                        cv2.imwrite(str(output/('%s_%02d.png'%(name,i))),side)
                    print('RG_SMOKE_PROBE|%s|empty=%d|excessive=%d'%(name,
                        report['methods'][-1]['empty_frames'],report['methods'][-1]['excessive_area_frames']),flush=True)
                    predictor.reset_state(state)
                    del state
            finally:
                cap.release()
            del predictor
            torch.cuda.empty_cache()
        report['status']='PROPOSALS_FOR_INDEPENDENT_REVIEW'
    except Exception as exc:
        report['status']='PROBE_FAILED_RELEASE_BLOCKED'
        report['error']=str(exc)
        (output/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
    finally:
        report['studio_changed']=before!=protected()
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        if (output/'frames').exists(): shutil.rmtree(output/'frames')
        if report['studio_changed']: raise ReviewRequired('PROTECTED_INPUT_CHANGED')


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--output',required=True)
    run(p.parse_args().output)
