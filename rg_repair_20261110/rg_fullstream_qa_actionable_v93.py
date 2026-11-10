"""RG V9.3: actionable notification QA evidence, never a coverage approval.

Extract exact rejected-candidate timecodes from a source-bound checkpoint and
summarize gaps where the host layout was not recognized. No video processing
and no side effects. The existing preflight BLOCK remains mandatory.
"""
from __future__ import annotations
from pathlib import Path
import json,re
COUNT_RE=re.compile(r'^POPUP_LAYOUT_VALID_SAMPLES_(\d+)_OF_(\d+)$')
def evidence_for_job(root,job):
    root=Path(root)
    flags=job.get('extra_review_flags') or []
    totals=[]
    for s in flags:
        match=COUNT_RE.fullmatch(str(s))
        if match:totals.append((int(match.group(1)),int(match.group(2))))
    # Aggregated checkpoint result is source-wide: never sum overlapping segment samples.
    recognized,total=(max(totals,key=lambda pair:pair[1]) if totals else (0,0))
    if recognized>total:raise RuntimeError('V93_LAYOUT_COUNTS_CORRUPT')
    rawpath=root/'completed_popups_v76.json'
    rejectpath=root/'V41_POPUP_VISUAL_REJECTIONS.json'
    raw=json.loads(rawpath.read_text(encoding='utf-8-sig')) if rawpath.is_file() else {}
    items=raw.get('result',{}).get('masks',[]) if isinstance(raw,dict) else []
    rejected=json.loads(rejectpath.read_text(encoding='utf-8-sig')) if rejectpath.is_file() else []
    if not isinstance(items,list) or not isinstance(rejected,list):raise RuntimeError('V93_INVALID_POPUP_EVIDENCE')
    if len(rejected)>len(items):raise RuntimeError('V93_REJECTIONS_EXCEED_CANDIDATES')
    duration=float(job.get('duration_seconds') or 0)
    unique=set();rows=[]
    for item in rejected:
        i=int(item['index'])
        if i in unique or i<0 or i>=len(items):raise RuntimeError('V93_INVALID_REJECTION_INDEX')
        unique.add(i)
        m=items[i]
        intervals=m.get('intervals') or []
        if len(intervals)!=1:raise RuntimeError('V93_REJECTION_INTERVALS_INVALID')
        start,end=map(float,intervals[0])
        if not (0<=start<end<=duration):raise RuntimeError('V93_REJECTION_OUT_OF_SOURCE_BOUNDS')
        rows.append({
            'candidate_index':i,
            'source_start_seconds':round(start,3),
            'source_end_seconds':round(end,3),
            'source_second':round((start+end)/2,3),
            'layout':str(m.get('layout','unknown')),
            'reason':str(item.get('reason','VISUAL_REJECTED')),
            'status':'HUMAN_VISUAL_CONFIRMATION_REQUIRED',
            'auto_approve':False})
    folder=root/'NOTIFICATION_QA_V93'
    return {
        'schema':'RG_SOURCE_BOUND_POPUP_REVIEW_V93',
        'source_scan_sampled_frames':total,
        'recognized_layout_samples':recognized,
        'unknown_layout_samples':total-recognized,
        'accepted_automated_masks':len(job.get('popup_masks') or []),
        'rejected_candidate_count':len(rows),
        'rejected_candidates':rows,
        'review_images':(
          {'rejections':str(folder/'895_three_rejected_candidates.jpg'),
           'unknown_layout':str(folder/'895_unknown_layout_samples_part_01.jpg')}
          if str(job.get('stream'))=='895' and folder.is_dir() else {}),
        'source_scan_not_full_content_coverage_proof':True,
        'popup_coverage_verified':False,
        'publish_ready':False,
        'auto_approve':False
    }
