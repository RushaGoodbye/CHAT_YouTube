#!/usr/bin/env python3
"""NEWS2 approved-media manifest gate. Read-only; no ffmpeg or Telegram calls.

Watermark approval is an immutable content hash and explicit visual policy.
There are deliberately NO default brand assets or assumed positions.
"""
import hashlib,json,os
from pathlib import Path

class MediaGateError(ValueError):pass
EXPECTED_SCHEMA='NEWS2_APPROVED_WATERMARK_MANIFEST_V1'
VALID_POSITIONS={'center'}
VALID_ASPECTS={'keep_aspect'}
APPROVED_NOV4_SHA='1e852e8540d079ebf275294a784559557098dab455f14bcfa1efe86152b73585'
APPROVED_PROFILE='RG_APPROVED_20261104_CENTER_040_078'
HEX=set('0123456789abcdef')

def digest(path,cap=15*1024*1024):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or not 8<=p.stat().st_size<=cap:
        raise MediaGateError('ASSET_MISSING_OR_UNSAFE')
    h=hashlib.sha256()
    with p.open('rb') as f:
        signature=f.read(8)
        if signature!=b'\x89PNG\r\n\x1a\n':
            raise MediaGateError('ASSET_NOT_PNG')
        h.update(signature)
        while True:
            block=f.read(1024*1024)
            if not block:break
            h.update(block)
    return h.hexdigest()

def verify(manifest,asset_path):
    if not isinstance(manifest,dict) or manifest.get('schema')!=EXPECTED_SCHEMA:
        raise MediaGateError('MANIFEST_SCHEMA')
    sha=manifest.get('approved_logo_sha256')
    if not isinstance(sha,str) or sha!=APPROVED_NOV4_SHA:
        raise MediaGateError('APPROVED_LOGO_HASH_NOT_PINNED')
    if manifest.get('position') not in VALID_POSITIONS:
        raise MediaGateError('POSITION_NOT_APPROVED')
    alpha=manifest.get('opacity_pct')
    size=manifest.get('width_pct')
    profile=manifest.get('watermark_profile')
    if type(alpha)!=int or alpha!=78:raise MediaGateError('APPROVED_OPACITY_78_REQUIRED')
    if type(size)!=int or size!=40:raise MediaGateError('APPROVED_WIDTH_40_REQUIRED')
    if profile!=APPROVED_PROFILE:raise MediaGateError('APPROVED_PROFILE_MISMATCH')
    if manifest.get('aspect')!='keep_aspect':raise MediaGateError('ASPECT_INVALID')
    if manifest.get('approved_by_user') is not True:
        raise MediaGateError('EXPLICIT_VISUAL_APPROVAL_REQUIRED')
    if digest(asset_path)!=sha:raise MediaGateError('LOGO_HASH_MISMATCH')
    return {
       'status':'APPROVED_WATERMARK_ASSET_VERIFIED',
       'logo_sha256':sha,
       'overlay_position':manifest['position'],
       'opacity_pct':alpha,
       'width_pct':size,
       'watermark_profile':profile,
       'telegram_calls':0,'publications':0,'writes':0,
    }

def selftest():
    import tempfile
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as d:
        f=Path(d)/'logo.png'
        f.write_bytes(b'\x89PNG\r\n\x1a\n'+b'isolated-test-only')
        profile={
          'schema':EXPECTED_SCHEMA,
          'approved_logo_sha256':APPROVED_NOV4_SHA,
          'watermark_profile':APPROVED_PROFILE,
          'position':'center',
          'opacity_pct':78,
          'width_pct':40,
          'aspect':'keep_aspect',
          'approved_by_user':True,
        }
        with patch(__name__+'.digest',return_value=APPROVED_NOV4_SHA):
            assert verify(profile,f)['status']=='APPROVED_WATERMARK_ASSET_VERIFIED'
            assert verify(profile,f)['overlay_position']=='center'
            for field,value in [('position','top_right'),('width_pct',20),('opacity_pct',60),('watermark_profile','UNKNOWN'),('approved_by_user',False),('approved_logo_sha256','0'*64)]:
                wrong=dict(profile);wrong[field]=value
                try:verify(wrong,f)
                except MediaGateError:pass
                else:raise AssertionError('MUST_REJECT_'+field)
        try:verify(profile,f)
        except MediaGateError:pass
        else:raise AssertionError('UNVERIFIED_LOGO_SHA_PASSED')
    print('NEWS2_NOV4_APPROVED_WATERMARK_8_CASES_PASS')
    print('NEWS2_CENTER_40_PERCENT_78_ALPHA_SHA256_GATE_PASS')

if __name__=='__main__':selftest()
