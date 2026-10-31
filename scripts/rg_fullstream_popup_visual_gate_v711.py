"""RG Full Stream V7.11: require independent visual review before popup blur.

Detection from geometry + temporal repetition is an untrusted *proposal*, never
permission to alter pixels. This module is pure, has no filesystem writes, and
never marks a video publish-ready. UI must provide independent review records
from a human; detector-generated fields are not review records.
"""
from __future__ import annotations
import math

def _num(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)

def _bounds(m):
    if not isinstance(m,dict): raise ValueError("POPUP_CANDIDATE_INVALID")
    x,y,w,h=(m.get(n) for n in ('x','y','width','height'))
    if not all(_num(n) for n in (x,y,w,h)) or min(w,h)<=0:
        raise ValueError("POPUP_GEOMETRY_INVALID")
    times=m.get('intervals')
    if not isinstance(times,list) or not times: raise ValueError("POPUP_INTERVAL_MISSING")
    for t in times:
        if not isinstance(t,(list,tuple)) or len(t)!=2 or not all(_num(a) for a in t) or t[1]<=t[0]:
            raise ValueError("POPUP_INTERVAL_INVALID")
    return (float(x),float(y),float(w),float(h)), [(float(a),float(b)) for a,b in times]

def _overlap(a,b):
    return max(0,min(a[1],b[1])-max(a[0],b[0]))

def classify(masks, reviews=(), *, require_manual=True):
    """Return approved masks only when separate editor evidence matches.

    A review record needs status=approved/rejected, source=editor_visual,
    seconds range, and geometry; detector flags themselves never authorize.
    An unknown or unlabeled mask is withheld. Provenance is a workflow contract,
    not cryptographic authentication; caller must keep review input separate
    from detector output and verify user/editor authorization.
    """
    if not isinstance(masks,list): raise ValueError("POPUP_MASKS_NOT_LIST")
    if not isinstance(reviews,(list,tuple)):raise ValueError("POPUP_REVIEWS_NOT_LIST")
    accepted=[]; rejected=[]; pending=[];unsafe=[]
    for i,m in enumerate(masks):
        g,intervals=_bounds(m)
        matches=[]
        for r in reviews:
            if not isinstance(r,dict) or r.get('source')!='editor_visual':continue
            r_status=r.get('status')
            if r_status not in ('approved','rejected'):continue
            try:
                rg,ts=_bounds(r)
            except ValueError:continue
            # Review must identify essentially the exact region and time, not
            # just any event in the stream. Protect against wrong-track reuse.
            if all(abs(a-b)<=10 for a,b in zip(g,rg)) and any(
                    _overlap(a,b)>=0.5*min(a[1]-a[0],b[1]-b[0])
                    for a in intervals for b in ts):
                matches.append(r_status)
        if 'rejected' in matches:
            rejected.append(i)
        elif len(matches)==1 and matches[0]=='approved' and require_manual:
            accepted.append(m)
        elif not require_manual:
            # Explicitly decline auto approval even if callers request it:
            # the observed RG895 detector has high false-positive recall.
            pending.append(i)
        elif len(matches)>1:
            unsafe.append(i)
        else:pending.append(i)
    return {'schema':'RG_POPUP_V711_EDITOR_REVIEW_GATE',
            'approved_masks':accepted,'approved_count':len(accepted),
            'rejected_indices':rejected,'pending_indices':pending,
            'ambiguous_indices':unsafe,
            'coverage_verified':False,
            'publish_ready':False,
            'status':'POPUP_COVERAGE_UNVERIFIED' if pending or unsafe else
                     ('POPUP_MASKS_REVIEWED_COVERAGE_STILL_UNVERIFIED'),
            'blur_safe_for_reviewed_candidates':bool(accepted) and not unsafe}
