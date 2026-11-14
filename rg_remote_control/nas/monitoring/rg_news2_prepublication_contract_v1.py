#!/usr/bin/env python3
"""NEWS2 pure prepublication gate. No filesystem, no Telegram, no callbacks.

Input records mirror the existing durable NEWS2 schema. Returned preview is
NOT permission to send: live channel identity and lock must be checked again
inside the actual publisher immediately before its exclusive receipt claim.
"""
import hashlib
import re
import time
from rg_news2_footer_entities_contract_v2 import append_footer,validate_footer

HEX24=re.compile(r'[0-9a-f]{24}\Z')
MEDIA_ID=re.compile(r'[A-Za-z0-9_-]{15,255}\Z')
class PublicationBlocked(ValueError):pass

def require(ok,why):
    if not ok:raise PublicationBlocked(why)

def gate(staging,private,decision,public,activation,now=None,video_receipt=None,video_file_hash=None):
    now=int(time.time()) if now is None else now
    require(type(now)==int,'BAD_TIME')
    require(isinstance(staging,dict) and isinstance(private,dict) and isinstance(decision,dict) and isinstance(activation,dict),'BAD_RECORDS')
    draft=staging.get('draft_id')
    require(isinstance(draft,str) and HEX24.fullmatch(draft),'BAD_DRAFT')
    require(all(x.get('draft_id')==draft for x in (private,decision)),'IDENTITY_MISMATCH')
    require(activation.get('status')=='ACTIVE','PUBLICATION_DISABLED')
    active=activation.get('activated_at')
    when=decision.get('timestamp')
    require(type(active)==int and type(when)==int and active<when<=now+60,'APPROVAL_NOT_CURRENT')
    require(now-when<=86400,'STALE_APPROVAL_REVIEW_REQUIRED')
    require(decision.get('schema')=='NEWS_RG_HUMAN_EDITORIAL_DECISION_V1','DECISION_SCHEMA')
    require(decision.get('decision')=='editorially_accepted_not_published','NOT_APPROVED')
    require(decision.get('public_publication')=='OFF' and staging.get('public_publication')=='OFF' and private.get('public_publication')=='OFF','PUBLICATION_CONTRACT_VIOLATED')
    require(staging.get('schema')=='NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1','STAGING_SCHEMA')
    require(private.get('status')=='PRIVATE_SENT_CONFIRMED','PRIVATE_DELIVERY_UNCERTAIN')
    require(private.get('message_id')==decision.get('telegram_message_id'),'MESSAGE_ID_MISMATCH')
    require(public is None,'PUBLIC_RECEIPT_ALREADY_EXISTS_NEVER_RETRY')
    media=staging.get('media_type')
    require(media in ('photo','video'),'UNSUPPORTED_MEDIA')
    caption=staging.get('proposed_text')
    require(isinstance(caption,str) and 60<=len(caption.strip())<=900,'CAPTION_CONTRACT')
    require('НЕВДАЛО' not in caption.upper() and not any(c in caption for c in 'ыъэёЫЪЭЁ'),'LANGUAGE_GATE')
    caption,entities=append_footer(caption)
    validate_footer(caption,entities)
    if media=='photo':
        require(staging.get('editorial_status')=='HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED','PHOTO_REVIEW_NOT_CONFIRMED')
        photo=private.get('telegram_photo_file_id')
        require(isinstance(photo,str) and MEDIA_ID.fullmatch(photo),'PHOTO_FILE_ID_MISSING')
        return {'status':'PHOTO_READY_FOR_LIVE_IDENTITY_RECHECK',
          'media_type':'photo','draft_id':draft,'caption':caption,
          'caption_entities':entities,'telegram_calls':0,'publications':0}
    require(staging.get('editorial_status')=='HUMAN_FACT_AND_VIDEO_REVIEW_REQUIRED','VIDEO_REVIEW_NOT_CONFIRMED')
    require(staging.get('watermark_required') is True,'WATERMARK_NOT_REQUIRED_UNSAFE')
    require(private.get('media_type')=='video','NOT_VIDEO_RECEIPT')
    require(isinstance(video_receipt,dict) and video_receipt.get('draft_id')==draft and video_receipt.get('status')=='NAS_WATERMARK_RENDERED','WATERMARK_RECEIPT_UNVERIFIED')
    require(video_receipt.get('telegram_delivery')=='NOT_SENT' and video_receipt.get('publication')=='OFF','VIDEO_ALREADY_HANDLED')
    expected=video_receipt.get('sha256')
    require(isinstance(expected,str) and re.fullmatch(r'[a-f0-9]{64}',expected),'WATERMARK_OUTPUT_SHA_MISSING')
    require(video_file_hash==expected,'WATERMARK_OUTPUT_SHA_MISMATCH')
    # Strict separate visual-approval/identity manifest must also pass prior
    # to live publication. A plain MP4 hash does not prove correct watermark.
    require(video_receipt.get('approved_visual_manifest_verified') is True,
            'WATERMARK_VISUAL_IDENTITY_NOT_VERIFIED')
    return {'status':'VIDEO_READY_FOR_LIVE_IDENTITY_RECHECK',
      'media_type':'video','draft_id':draft,'caption':caption,
      'caption_entities':entities,'telegram_calls':0,'publications':0}

def selftest():
    d='a'*24;now=1794660000
    a={'schema':'NEWS_RG_HUMAN_EDITORIAL_DECISION_V1','decision':'editorially_accepted_not_published',
       'public_publication':'OFF','draft_id':d,'telegram_message_id':123,'timestamp':now-30}
    s={'schema':'NEWS_RG_PRIVATE_EDITORIAL_STAGING_V1','draft_id':d,'public_publication':'OFF',
       'editorial_status':'HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED','media_type':'photo',
       'proposed_text':'Українська новина про події в регіоні з перевіреними деталями та посиланням на джерело.'}
    p={'draft_id':d,'status':'PRIVATE_SENT_CONFIRMED','message_id':123,'public_publication':'OFF','telegram_photo_file_id':'Z'*50}
    active={'status':'ACTIVE','activated_at':now-1000}
    from copy import deepcopy
    assert gate(s,p,a,None,active,now)['status']=='PHOTO_READY_FOR_LIVE_IDENTITY_RECHECK'
    r=deepcopy(a);r['decision']='editorially_rejected'
    try:gate(s,p,r,None,active,now)
    except PublicationBlocked as e:assert str(e)=='NOT_APPROVED'
    else:raise AssertionError('REJECT_WAS_ELIGIBLE')
    try:gate(s,p,a,{'status':'PUBLIC_SEND_UNCERTAIN_NO_RETRY'},active,now)
    except PublicationBlocked as e:assert str(e)=='PUBLIC_RECEIPT_ALREADY_EXISTS_NEVER_RETRY'
    else:raise AssertionError('UNCERTAIN_RECEIPT_RETRIED')
    try:gate(s,p,a,None,active,now+90000)
    except PublicationBlocked as e:assert str(e)=='STALE_APPROVAL_REVIEW_REQUIRED'
    else:raise AssertionError('STALE_APPROVAL_PASSED')
    video_s=deepcopy(s);video_s.update(media_type='video',editorial_status='HUMAN_FACT_AND_VIDEO_REVIEW_REQUIRED',watermark_required=True)
    video_p=deepcopy(p);video_p['media_type']='video'
    v={'draft_id':d,'status':'NAS_WATERMARK_RENDERED','telegram_delivery':'NOT_SENT','publication':'OFF',
       'sha256':'a'*64}
    try:gate(video_s,video_p,a,None,active,now,v,'a'*64)
    except PublicationBlocked as e:assert str(e)=='WATERMARK_VISUAL_IDENTITY_NOT_VERIFIED'
    else:raise AssertionError('UNVERIFIED_WATERMARK_PASSED')
    v['approved_visual_manifest_verified']=True
    assert gate(video_s,video_p,a,None,active,now,v,'a'*64)['status']=='VIDEO_READY_FOR_LIVE_IDENTITY_RECHECK'
    print('NEWS2_PREPUBLICATION_GATE_6_CASES_PASS')
    print('NEWS2_REJECT_STALE_UNCERTAIN_UNAPPROVED_WM_BLOCKED_PASS')

if __name__=='__main__':selftest()
