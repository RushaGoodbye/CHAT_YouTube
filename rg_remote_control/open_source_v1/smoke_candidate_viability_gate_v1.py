#!/usr/bin/env python3
"""Candidate smoke QC. Coarse region evidence is insufficient for release."""
import argparse,json,pathlib

MAX_MEAN_PIXELS=18000  # exploratory only, ROI 740x610; not a validated limit
MAX_CONTROL_FRACTION=.03

def evaluate(rows):
    result=[]
    for m in rows:
        reasons=[]
        if m.get('tested_smoke_regions')!=7:
            reasons.append('SMOKE_EVIDENCE_CASES_MISSING')
        if m.get('smoke_regions_with_zero_candidates',7)>0:
            reasons.append('VISIBLE_SMOKE_REGION_MISSED')
        if m.get('mean_candidate_mask_pixels',float('inf'))>MAX_MEAN_PIXELS:
            reasons.append('EXCESSIVE_CANDIDATE_AREA')
        if m.get('control_candidate_fraction',1)>MAX_CONTROL_FRACTION:
            reasons.append('BLEED_IN_COARSE_CONTROL_REGIONS')
        reasons += ['SMOKE_PIXEL_IDENTITY_NOT_VERIFIED','8865_FULL_NEGATIVE_NOT_VERIFIED']
        result.append({'method':m['method'],'status':'REJECT_FOR_PRODUCTION',
                       'reasons':reasons,'production_release_allowed':False})
    return result

def self_test():
    good={'method':'synthetic','tested_smoke_regions':7,
          'smoke_regions_with_zero_candidates':0,'mean_candidate_mask_pixels':5000,
          'control_candidate_fraction':0}
    bad=dict(good,mean_candidate_mask_pixels=99000,control_candidate_fraction=.57)
    assert 'EXCESSIVE_CANDIDATE_AREA' in evaluate([bad])[0]['reasons']
    assert 'BLEED_IN_COARSE_CONTROL_REGIONS' in evaluate([bad])[0]['reasons']
    assert 'SMOKE_PIXEL_IDENTITY_NOT_VERIFIED' in evaluate([good])[0]['reasons']
    assert all(not x['production_release_allowed'] for x in evaluate([good,bad]))
    print('RG_SMOKE_CANDIDATE_VIABILITY_GATE_SELFTEST_PASS')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=pathlib.Path)
    p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.self_test:self_test()
    elif a.input:
        d=json.loads(a.input.read_text(encoding='utf-8'))
        if d.get('schema')!='RG_892_SMOKE_CANDIDATE_METHOD_COMPARE_V1':
            raise ValueError('Incorrect report schema')
        print(json.dumps({'schema':'RG_892_SMOKE_CANDIDATE_VIABILITY_GATE_V1',
            'methods':evaluate(d['summary']),'production_release_allowed':False},
            ensure_ascii=False,indent=2))
    else:p.error('--self-test or --input required')
