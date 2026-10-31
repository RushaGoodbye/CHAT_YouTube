"""V7.11 candidate: conservative small transient popup fallback.

This is a SHA-pinned source transformation, NOT an installer. It does not write
anything on import, and never touches video, XML, dialogue outputs, or queues.
Use only after temporal and full-stream shadow tests on real footage.
"""
from __future__ import annotations
import ast
import hashlib

EXPECTED_SHA = '2f7c07dc64ed3d3d7030d2695a1675ad52c2614a60749e30e3244f6d7284c370'
ANCHOR = '    return selected\n\n\ndef scan_popups('

# The original strict detector takes priority. The fallback is restricted to
# narrow UI cards within the existing lower-right host ROI. The existing
# scan_popups timeline tracker separately requires two consecutive hits and
# suppresses persistent decoration before any mask is generated.
FALLBACK = '''    if not selected:
        compact=[]
        for contour in contours:
            bx,by,bw,bh=cv2.boundingRect(contour)
            if not (110<=bw<150 and 25<=bh<=85 and bw>=bh*1.7):continue
            if bx<5 or by<5 or bx+bw>roi.shape[1]-6 or by+bh>roi.shape[0]-6:continue
            inside=roi[by+5:by+bh-5,bx+5:bx+bw-5]
            if inside.size<2000:continue
            ig=cv2.cvtColor(inside,cv2.COLOR_BGR2GRAY)
            edge_density=float(np.mean(cv2.Canny(ig,50,125)>0))
            if not (.012<edge_density<.28):continue
            if not (np.mean(ig>185)>.007 and np.mean(ig<105)>.045):continue
            compact.append((bx+x0,by+y0,bw,bh))
        compact.sort(key=lambda v:v[2]*v[3],reverse=True)
        return compact[:1]
    return selected


def scan_popups('''


def patch_source(original: bytes) -> bytes:
    if hashlib.sha256(original).hexdigest() != EXPECTED_SHA:
        raise RuntimeError('RG_V711_DETECTOR_SHA_DRIFT_FAIL_CLOSED')
    data = original.decode('utf-8-sig')
    if data.count(ANCHOR) != 1:
        raise RuntimeError('RG_V711_DETECTOR_RETURN_ANCHOR_NOT_UNIQUE')
    modified = data.replace(ANCHOR, FALLBACK, 1)
    ast.parse(modified)
    return modified.encode('utf-8-sig') if original.startswith(b'\xef\xbb\xbf') else modified.encode('utf-8')


def verify_sources(original: bytes, patched: bytes) -> None:
    a=original.decode('utf-8-sig');b=patched.decode('utf-8-sig')
    if b.count('def popup_candidates(')!=1 or b.count('def scan_popups(')!=1:
        raise RuntimeError('RG_V711_DECLARATION_CARDINALITY_FAILURE')
    if len(b)<=len(a) or 'if not selected:\n        compact=[]' not in b:
        raise RuntimeError('RG_V711_SMALL_POPUP_PATCH_ABSENT')
    if 'if t[\'count\']<2:continue' not in b:
        raise RuntimeError('RG_V711_TEMPORAL_TRACKING_LOST')
    if 'suppress_persistent_popup_lookalikes(source,masks)' not in b:
        raise RuntimeError('RG_V711_STATIC_DECORATION_GUARD_LOST')
    if 'popup_search_area(layout)' not in b:
        raise RuntimeError('RG_V711_HOST_ROI_GUARD_LOST')