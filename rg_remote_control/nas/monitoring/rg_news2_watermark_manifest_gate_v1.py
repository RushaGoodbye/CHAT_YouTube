#!/usr/bin/env python3
"""NEWS2 approved-media manifest gate. Read-only; no ffmpeg or Telegram calls.

Watermark approval is an immutable content hash and explicit visual policy.
There are deliberately NO default brand assets or assumed positions.
"""
import hashlib,json,os
from pathlib import Path

class MediaGateError(ValueError):pass
EXPECTED_SCHEMA='NEWS2_APPROVED_WATERMARK_MANIFEST_V1'
VALID_POSITIONS={'top_right'}
VALID_ASPECTS={'keep_aspect'}
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
    if not isinstance(sha,str) or len(sha)!=64 or any(c not in HEX for c in sha):
        raise MediaGateError('APPROVED_LOGO_HASH_NOT_PINNED')
    if manifest.get('position') not in VALID_POSITIONS:
        raise MediaGateError('POSITION_NOT_APPROVED')
    alpha=manifest.get('opacity_pct')
    size=manifest.get('width_pct')
    x=manifest.get('margin_x_pct')
    y=manifest.get('margin_y_pct')
    if type(alpha)!=int or alpha!=78:raise MediaGateError('APPROVED_OPACITY_78_REQUIRED')
    if type(size)!=int or size!=20:raise MediaGateError('APPROVED_WIDTH_20_REQUIRED')
    if type(x)!=int or type(y)!=int or x!=3 or y!=3:
        raise MediaGateError('APPROVED_MARGIN_THREE_PERCENT_REQUIRED')
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
       'margin_x_pct':x,
       'margin_y_pct':y,
       'telegram_calls':0,'publications':0,'writes':0,
    }

def selftest():
    import tempfile
    # Selftest PNG signature only (media rendering is tested separately).
    with tempfile.TemporaryDirectory() as d:
        file=Path(d)/'sample.png'
        file.write_bytes(b'\x89PNG\r\n\x1a\n'+b'test-only-sample-asset')
        h=digest(file)
        v={
          'schema':EXPECTED_SCHEMA,'approved_logo_sha256':h,'position':'top_right',
          'opacity_pct':78,'width_pct':20,'margin_x_pct':3,'margin_y_pct':3,
          'aspect':'keep_aspect','approved_by_user':True,
        }
        assert verify(v,file)['status']=='APPROVED_WATERMARK_ASSET_VERIFIED'
        v['approved_logo_sha256']='0'*64
        try:verify(v,file)
        except MediaGateError as e:assert str(e)=='LOGO_HASH_MISMATCH'
        else:raise AssertionError('HASH_MISMATCH_NOT_REJECTED')
        v['approved_logo_sha256']=h;v['approved_by_user']=False
        try:verify(v,file)
        except MediaGateError as e:assert str(e)=='EXPLICIT_VISUAL_APPROVAL_REQUIRED'
        else:raise AssertionError('UNAPPROVED_VISUAL_PASSED')
        v['approved_by_user']=True;v['position']='bottom_right'
        try:verify(v,file)
        except MediaGateError as e:assert str(e)=='POSITION_NOT_APPROVED'
        else:raise AssertionError('POSITION_NOT_REJECTED')
    print('NEWS2_WATERMARK_MANIFEST_GATE_4_CASES_PASS')
    print('NEWS2_UNVERIFIED_LOGO_OR_POSITION_REJECTED_PASS')

if __name__=='__main__':selftest()
