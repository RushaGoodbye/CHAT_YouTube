"""Actual installed Studio COPY, all green legacy sidecars, real mask render.

Produces a failed-quality diagnostic candidate and verifies it cannot export.
No installer or command targeting the live Studio is part of this workflow.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import traceback
import zipfile
from rg_smoking_compliance import VERSION,ReviewRequired,sha256_file
from rg_smoking_stage import stage_app
from rg_smoking_media import render_candidate
from rg_smoking_xml import write_candidate
from run_real_four_layer_qa import APP,ROOT,SOURCE,HOLD,preflight,protected


def run(output):
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    before=protected(); report=dict(schema='RG_SMOKING_STUDIO_INTEGRATION_QA_V1',
        version=VERSION,status='RUNNING',release_allowed=False,production_installed=False)
    try:
        preflight()
        report['staging']=stage_app(APP,output/'staged_app')
        sys.path.insert(0,str(output/'staged_app'))
        spec=importlib.util.spec_from_file_location('_actual_staged_release_gate',output/'staged_app/rg_final_release_gate.py')
        gate=importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
        fixture=output/'legacy_all_green_test'; fixture.mkdir()
        # Deliberate synthetic claims live only in this fixture directory.
        # Validate is mocked for this regression so the smoking gate is the
        # sole failing gate rather than an unrelated structural XML failure.
        name=fixture/'RG_EDITED_892_4.xml'; name.write_text('<xmeml/>')
        for suffix in ('FINAL_TIMELINE_AUDIT','CIGARETTE_BLUR_QA','CAMERA_TRANSITION_QA',
                'PRIVACY_BLUR_QA','DIRECTOR_QA','VOICE_LEVEL_MATCH'):
            (fixture/(name.stem+'_'+suffix+'.json')).write_text(json.dumps(
                dict(passed=True,coverage=1.0,synthetic_fixture_only=True)),encoding='utf-8')
        validate=gate.validate; gate.validate=lambda p:{'synthetic_fixture_only':True}
        try: legacy_result=gate.evaluate(name)
        finally: gate.validate=validate
        if legacy_result['passed'] or legacy_result['failures']!=['SMOKING_COMPLIANCE_REVIEW_REQUIRED']:
            raise ReviewRequired('LEGACY_PASS_BYPASSED_FOUR_LAYER_GATE')
        report['legacy_all_green_export_blocked']=True
        report['legacy_false_pass_regression']=legacy_result
        sys.path.insert(0,str(Path(__file__).parents[1]/'open_source_v1'))
        from audit_886_5_dialogue_preflight_v1 import verify_quarantine
        _,clean,_=verify_quarantine()
        clean_copy=fixture/'RG_EDITED_886_5.candidate.xml'; shutil.copyfile(clean,clean_copy)
        quarantined=gate.evaluate(clean_copy)
        if quarantined['passed'] or '886_5_QUARANTINED_NO_EXPORT' not in quarantined['checks']['smoking_compliance']['failures']:
            raise ReviewRequired('QUARANTINE_BYPASSED_STAGED_GATE')
        report['quarantine_actual_studio_gate_blocked']=True
        report['withheld_clean_xml_validator']=quarantined['checks']['premiere_xml']
        # Reuse the pinned real 60-frame experiment, never promote its smoke
        # envelope, unconditional mouth or manual prompts to semantic truth.
        archive=ROOT/'smoking_release_candidate_v1/1a9e4537034d7fe0460ffced3f47bb351df1e186/RG_SMOKING_REAL_FOUR_LAYER_CANDIDATE_QA_V1.zip'
        real=output/'real_892_diagnostic'; real.mkdir()
        with zipfile.ZipFile(archive) as z:
            if z.testzip() is not None: raise ReviewRequired('REAL_MASK_FIXTURE_CORRUPT')
            for name in ('scan.json','four_layers_packed.npz'): z.extract(name,real)
        masks=real/'four_layers_packed.npz'
        if sha256_file(masks)!='da0857a04959b6a8c47f68593bb5ed89ca9df94dbe16052d13c879c5ba3c771b':
            raise ReviewRequired('REAL_MASK_FIXTURE_CHANGED')
        scan=json.loads((real/'scan.json').read_text(encoding='utf-8'))
        scan.update(version=VERSION,source_shape_hw=[1080,1920],roi_xyxy=[1020,65,1660,775],
            mask_policy=dict(max_area_fraction=.12,padding_px=12,feather_px=4,blur_sigma=30))
        (real/'candidate_scan.json').write_text(json.dumps(scan,indent=2),encoding='utf-8')
        derivative=render_candidate(SOURCE,scan,masks,real/'892_60frames.candidate.mov',[360,420])
        report['real_892_lossless_render']=derivative
        original=real/'source_plan.xml'
        original.write_text('''<?xml version="1.0"?><!DOCTYPE xmeml><xmeml version="4"><sequence>
        <name>DIAGNOSTIC_NOT_DELIVERY</name><duration>60</duration><rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>
        <media><video><track><clipitem id="real-test-v1"><start>0</start><end>60</end><in>360</in><out>420</out>
        <file id="real-test-source"><pathurl>%s</pathurl><duration>720</duration><media><video><samplecharacteristics>
        <width>1920</width><height>1080</height></samplecharacteristics></video></media></file>
        </clipitem></track></video></media></sequence></xmeml>'''%SOURCE.as_uri(),encoding='utf-8')
        candidate=real/'RG_EDITED_892_999.candidate.xml'
        report['real_candidate_xml']=write_candidate(original,[derivative],candidate,'892_999')
        report['candidate_staged_gate']=gate.evaluate(candidate)
        if report['candidate_staged_gate']['passed']:
            raise ReviewRequired('UNREVIEWED_REAL_RENDER_WRONGLY_RELEASED')
        report['real_encoded_frames_exactly_match_four_layer_compositor']=60
        report['real_source_pixels_outside_alpha_unchanged_after_encoding']=True
        report['real_candidate_audio_streams']=0
        report['status']='INTEGRATION_INVARIANTS_PASSED_SEMANTIC_RELEASE_BLOCKED'
    except Exception as exc:
        report['status']='INTEGRATION_FAILED_RELEASE_BLOCKED'; report['error']=str(exc)
        (output/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
    finally:
        report['studio_changed']=protected()!=before
        report['quarantine_886_5_unchanged']=before.get(str(HOLD))==sha256_file(HOLD)
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('RG_STUDIO_INTEGRATION_QA|'+json.dumps({k:report.get(k) for k in ('status','release_allowed',
            'production_installed','studio_changed','quarantine_886_5_unchanged','real_encoded_frames_exactly_match_four_layer_compositor')}),flush=True)
        if report['studio_changed']: raise ReviewRequired('PROTECTED_STUDIO_CHANGED')


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--output',required=True)
    run(p.parse_args().output)
