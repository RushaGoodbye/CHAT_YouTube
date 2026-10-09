"""Bounded real 892 candidate. Uses existing offline models in isolated F: venv.

All seeds describe this exact test scene, not a general smoking detector.
The smoke envelope is an explicitly unvalidated proposal. Release is blocked
until independent full-scene review and smoke/phase verification succeed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

from rg_smoking_compliance import (LAYERS, SCHEMA, VERSION, MaskPolicy,
    ReviewRequired, blur_frame, compose_masks, evaluate_scan, sha256_file)

ROOT = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow")
SOURCE = ROOT / "positive_892_015841_v1/892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4"
MODEL = ROOT / "sam2_native_windows_892_v1/sam2.1_hiera_tiny.pt"
CONFIG = ROOT / "sam2_native_windows_892_v1/sam2_repo/sam2/configs"
YUNET = ROOT / "model_cache_yunet_v1/face_detection_yunet_2023mar.onnx"
APP = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
HOLD = APP / "886/RG_EDITED_886_5.SEMANTIC_HOLD.json"
SOURCE_SHA = "bf2e3e585afeaa0b0ba3c347066a6ca1adcacfec282cba691cc7ec9d1ae3b49c"
MODEL_SHA = "7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69"
YUNET_SHA = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
COUNT, START = 60, 360
CIGARETTE_SEED = [(1248, 423, 1), (1290, 459, 0), (1200, 425, 0)]
GRIP_SEED = [(1305,635,1),(1365,595,1),(1413,534,1),(1475,489,0),
    (1558,500,0),(1160,460,0),(1373,524,1),(1409,491,1),
    (1446,485,1),(1470,406,0),(1512,515,0)]


def protected():
    files = list(APP.glob("*.py")) + list(APP.glob("*.xml"))
    files += list((APP / "886").glob("*.xml")) + list(APP.glob("rg_auto_edit_config.json"))
    files += list(APP.glob("*HOLD*.json")) + list((APP / "886").glob("*HOLD*.json"))
    return {str(p): sha256_file(p) for p in sorted(set(files)) if p.is_file()}


def preflight():
    for path, expected in ((SOURCE, SOURCE_SHA), (MODEL, MODEL_SHA), (YUNET, YUNET_SHA)):
        if not path.is_file() or sha256_file(path) != expected:
            raise ReviewRequired("PINNED_INPUT_CHANGED:" + path.name)
    hold = json.loads(HOLD.read_text(encoding="utf-8-sig"))
    for key, val in (("do_not_publish", True), ("primary_xml_withheld", True),
                     ("delivered_xml_withheld", True)):
        if hold.get(key) is not val:
            raise ReviewRequired("886_5_QUARANTINE_INVALID")
    if (APP / "RG_EDITED_886_5.xml").exists() or (APP / "886/RG_EDITED_886_5.xml").exists():
        raise ReviewRequired("886_5_PUBLISHABLE_XML_UNEXPECTED")
    if not (CONFIG / "sam2.1/sam2.1_hiera_t.yaml").is_file():
        raise ReviewRequired("PINNED_SAM2_CONFIGURATION_MISSING")


def extract_frames(stage):
    import cv2
    cap = cv2.VideoCapture(str(SOURCE))
    if not cap.isOpened() or abs(cap.get(cv2.CAP_PROP_FPS) - 30) > .001:
        raise ReviewRequired("SOURCE_FPS_UNSUPPORTED")
    folder = stage / "frames"
    folder.mkdir()
    cap.set(cv2.CAP_PROP_POS_FRAMES, START)
    try:
        for i in range(COUNT):
            ok, im = cap.read()
            if not ok or im.shape != (1080,1920,3):
                raise ReviewRequired("SOURCE_FRAME_MISSING")
            if not cv2.imwrite(str(folder / ("%05d.jpg" % i)), im,
                               [cv2.IMWRITE_JPEG_QUALITY,100]):
                raise ReviewRequired("FRAME_STAGING_FAILED")
    finally:
        cap.release()
    return folder


def sam_tracks(folder):
    import numpy as np
    import torch
    from hydra import initialize_config_dir
    from hydra.core.global_hydra import GlobalHydra
    from sam2.build_sam import build_sam2_video_predictor
    if not torch.cuda.is_available() or torch.__version__.split('+')[0] != '2.8.0':
        raise ReviewRequired("PINNED_CUDA_RUNTIME_UNAVAILABLE")
    free, _ = torch.cuda.mem_get_info()
    if free < 4 * 1024**3:
        raise ReviewRequired("INSUFFICIENT_FREE_VRAM")
    GlobalHydra.instance().clear()
    initialize_config_dir(version_base="1.2", config_dir=str(CONFIG.resolve(strict=True)))
    with torch.inference_mode():
        predictor = build_sam2_video_predictor('sam2.1/sam2.1_hiera_t.yaml',
            str(MODEL), device='cuda', apply_postprocessing=False)
        masks = {}
        for name, seed, first, reverse in (
            ('cigarette', CIGARETTE_SEED, 0, False),
            ('grip', GRIP_SEED, COUNT-1, True)):
            state = predictor.init_state(str(folder), offload_video_to_cpu=True,
                offload_state_to_cpu=True, async_loading_frames=False)
            predictor.add_new_points_or_box(state, frame_idx=first, obj_id=1,
                points=np.asarray([p[:2] for p in seed],np.float32),
                labels=np.asarray([p[2] for p in seed],np.int32))
            result = {}
            for frame, ids, logits in predictor.propagate_in_video(state,
                    start_frame_idx=first, max_frame_num_to_track=COUNT-1, reverse=reverse):
                i = int(frame)
                if not 0 <= i < COUNT or 1 not in ids or i in result:
                    raise ReviewRequired("SAM2_INVALID_TRACK_FRAME")
                raw = (logits[list(ids).index(1)] > 0).detach().cpu().numpy().squeeze()
                if raw.shape != (1080,1920) or not raw.any():
                    raise ReviewRequired("SAM2_TRACK_LOST:" + name)
                result[i] = np.asarray(raw, dtype=bool)
                if i % 10 == 0:
                    print("RG_SMOKING_TRACK|%s|frame=%d|pixels=%d" % (name,i,raw.sum()),flush=True)
            if set(result) != set(range(COUNT)):
                raise ReviewRequired("SAM2_INCOMPLETE_TRACK:" + name)
            masks[name] = result
            predictor.reset_state(state)
            del state
        del predictor
        torch.cuda.empty_cache()
    return masks


def candidate_masks(frame, i, tracks, detector, plume_history):
    import cv2
    import numpy as np
    cigar = tracks['cigarette'][i]
    hand = tracks['grip'][i]
    # Keep the grip near the tracked cigarette rather than the entire palm.
    near = cv2.dilate(cigar.astype(np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(251,251))).astype(bool)
    grip = hand & near
    scaled = cv2.resize(frame[270:710,1100:1650], (550,440))
    _, faces = detector.detect(scaled)
    if faces is None or not len(faces):
        raise ReviewRequired("MOUTH_LANDMARKS_LOST")
    f = faces[int(np.argmax(faces[:,14]))]
    cx, cy = int(round((f[10]+f[12])*.5+1100)), int(round((f[11]+f[13])*.5+270))
    half_width = max(38, int(round(abs(f[12]-f[10])*.65)))
    mouth = np.zeros((1080,1920),np.uint8)
    cv2.ellipse(mouth,(cx,cy),(half_width,32),0,0,360,1,-1)
    yy, xx = np.nonzero(cigar)
    # Thin, translucent smoke lacks independently verified segmentation in the
    # existing models. Preserve that fact. This local envelope is QA only.
    plume_history.append((int(xx.min()),int(yy.min())))
    origin_x = min(p[0] for p in plume_history[-45:])
    origin_y = min(p[1] for p in plume_history[-45:])
    smoke = np.zeros((1080,1920),np.uint8)
    left, right = max(1090,origin_x-115), min(1390,origin_x+105)
    top, bottom = max(115,origin_y-310), min(455,origin_y+25)
    smoke[top:bottom,left:right] = 1
    return {'cigarette':cigar, 'grip':grip, 'smoke':smoke.astype(bool),
            'mouth':mouth.astype(bool)}, {'mouth_center_xy':[cx,cy],
            'mouth_width_px':half_width*2,
            'smoke_proposal_xyxy':[left,top,right,bottom]}


def run(output):
    preflight()
    before = protected()
    output = Path(output).resolve()
    if output.exists():
        raise ReviewRequired("REFUSE_OVERWRITING_PRIOR_QA")
    output.parent.mkdir(parents=True,exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.smoking-four-layer-',dir=str(output.parent)))
    try:
        import cv2
        import numpy as np
        folder = extract_frames(stage)
        tracks = sam_tracks(folder)
        detector = cv2.FaceDetectorYN.create(str(YUNET),'',(550,440),
            score_threshold=.55,nms_threshold=.3,top_k=200)
        if detector is None:
            raise ReviewRequired("YUNET_LOAD_FAILED")
        policy = MaskPolicy(max_area_fraction=.12,padding_px=12,feather_px=4,blur_sigma=30)
        roi = (1020,65,1660,775)
        crop = (1060,90,1660,760)
        packed = {k:[] for k in LAYERS}
        rows, metrics, history, contact = [],[],[],[]
        writer = cv2.VideoWriter(str(stage/'four_layer_review.mp4'),
            cv2.VideoWriter_fourcc(*'mp4v'),30,(1200,670))
        if not writer.isOpened():
            raise ReviewRequired("REVIEW_VIDEO_WRITER_UNAVAILABLE")
        # Decode originals for render; lossy staged SAM2 frames are never used as
        # the source of a final preview, nor counted as exact source frame hashes.
        cap = cv2.VideoCapture(str(SOURCE))
        cap.set(cv2.CAP_PROP_POS_FRAMES,START)
        try:
            for i in range(COUNT):
                ok, im = cap.read()
                if not ok:
                    raise ReviewRequired("SOURCE_RENDER_FRAME_MISSING")
                layers, observations = candidate_masks(im,i,tracks,detector,history)
                required = {k:True for k in LAYERS}
                alpha, m = compose_masks(layers,required,(1080,1920),roi,policy=policy)
                after = blur_frame(im,alpha,policy)
                if not np.array_equal(after[alpha==0], im[alpha==0]):
                    raise ReviewRequired("UNRELATED_SOURCE_PIXELS_CHANGED")
                for key in LAYERS:
                    packed[key].append(np.packbits(layers[key],axis=1))
                digest = hashlib.sha256(b''.join(layers[k].tobytes() for k in LAYERS)).hexdigest()
                rows.append(dict(source_frame=START+i,state='CONFIRMED_SMOKING',
                    required=required,layer_pixels={k:m['layers'][k]['pixels'] for k in LAYERS},
                    local_mask_guard_passed=True,mask_sha256=digest,
                    decoded_frame_sha256=hashlib.sha256(im.tobytes()).hexdigest()))
                metrics.append(dict(frame=START+i,**m,**observations))
                x0,y0,x1,y1 = crop
                side = np.concatenate([im[y0:y1,x0:x1],after[y0:y1,x0:x1]],axis=1)
                writer.write(side)
                if i in (0,10,20,30,40,50,59):
                    cv2.imwrite(str(stage/('review_%02d.png'%i)),side)
                    contact.append(cv2.resize(side,(720,402)))
                if i % 10 == 0:
                    print('RG_SMOKING_COMPOSE|frame=%d|area=%.5f'%(i,m['mask_area_fraction']),flush=True)
        finally:
            cap.release()
            writer.release()
        np.savez_compressed(stage/'four_layers_packed.npz',
            **{k:np.asarray(v,dtype=np.uint8) for k,v in packed.items()})
        scan = dict(schema=SCHEMA,version=VERSION,source_sha256=SOURCE_SHA,
            source_ranges_frames=[[START,START+COUNT]],dialogue='892_test_scene',
            inference_completed=True,frames=rows,
            failures=['SMOKE_SEGMENTATION_NOT_INDEPENDENTLY_VERIFIED',
                'CONDITIONAL_MOUTH_PHASE_NOT_INDEPENDENTLY_VERIFIED',
                'MANUAL_TEST_SCENE_SEEDS_NOT_AUTOMATIC_DETECTION'])
        gate = evaluate_scan(scan,source_sha256=SOURCE_SHA,ranges=[[START,START+COUNT]],
            dialogue='892_test_scene')
        if gate['release_allowed']:
            raise ReviewRequired('QA_CANDIDATE_WRONGLY_APPROVED')
        report = dict(schema='RG_SMOKING_REAL_FOUR_LAYER_CANDIDATE_QA_V1',
            status='FOUR_LAYER_PREVIEW_CREATED_RELEASE_BLOCKED',version=VERSION,
            source_sha256=SOURCE_SHA,model_sha256=MODEL_SHA,yunet_sha256=YUNET_SHA,
            frames=COUNT,fps=30,source_frame_start=START,source_frame_end=START+COUNT-1,
            lossless_binary_layers_saved=True,metrics=metrics,
            mask_archive_sha256=sha256_file(stage/'four_layers_packed.npz'),
            smoke_mask_method='UNVALIDATED_LOCAL_ENVELOPE',
            mouth_phase_method='KNOWN_SMOKING_SCENE_CANDIDATE_NOT_CALIBRATED',
            release_gate=gate,production_release_allowed=False,
            studio_changed=before!=protected(),quarantine_886_5_unchanged=before.get(str(HOLD))==sha256_file(HOLD),
            source_video_changed=sha256_file(SOURCE)!=SOURCE_SHA,
            source_audio_changed=False,premiere_xml_changed=False)
        if report['studio_changed'] or report['source_video_changed'] or not report['quarantine_886_5_unchanged']:
            raise ReviewRequired('PROTECTED_INPUT_CHANGED_DURING_QA')
        (stage/'scan.json').write_text(json.dumps(scan,indent=2),encoding='utf-8')
        (stage/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        # ZIP has replay source and lossless masks, so metrics are independently
        # reproducible. Review PNGs accompany the video at original source scale.
        archive = stage/'RG_SMOKING_REAL_FOUR_LAYER_CANDIDATE_QA_V1.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(stage.iterdir()):
                if p.is_file() and p!=archive:
                    z.write(p,p.name)
            for script in (Path(__file__),Path(__file__).with_name('rg_smoking_compliance.py')):
                z.write(script,'replay/'+script.name)
        with zipfile.ZipFile(archive) as z:
            if z.testzip() is not None:
                raise ReviewRequired('CANDIDATE_ARCHIVE_CRC_FAILED')
        shutil.rmtree(folder)
        stage.rename(output)
        print(json.dumps({'status':report['status'],'frames':COUNT,
            'archive':str(output/archive.name),'release_allowed':False,
            'studio_changed':False,'quarantine_886_5_unchanged':True}),flush=True)
    finally:
        if before != protected():
            raise ReviewRequired('PROTECTED_INPUT_CHANGED')
        if stage.exists():
            shutil.rmtree(stage)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--output',required=True)
    args=p.parse_args()
    run(args.output)
