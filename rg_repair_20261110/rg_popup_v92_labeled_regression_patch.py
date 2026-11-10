"""RG Popup V9.2: conservative card threshold tuned on user-reviewed 885.

10 editor-confirmed popup rectangles, 15 distinct editor-unselected candidate
rectangles. Changes only V41 card appearance verification. The upstream
two-frame candidate scan, layout confirmation, static lookalike suppressor
and downstream editorial QA block remain unchanged.

Safe installation only when Studio fullstream worker lock IDLE, full backups
and exact hash-pin replacement. No video/audio processing in this script.
"""
from __future__ import annotations
import ast,hashlib,os,sys,uuid,time,argparse
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
DETECTOR="rg_fullstream_detectors_v2.py"
BATCH="rg_fullstream_batch_v53.py"
OLD_GREY="""grey_card=(65<=median<=165 and spread>=60 and bright>=.34
                       and saturation<=115 and edge>=.068 and detail>=850)"""
NEW_GREY="""grey_card=(45<=median<=165 and spread>=48 and bright>=.22
                       and saturation<=140 and edge>=.065 and detail>=650)"""
OLD_RED="""red_card=(50<=median<=95 and spread>=58 and bright>=.10
                      and saturation>=160 and edge>=.09 and detail>=1200)"""
NEW_RED="""red_card=(45<=median<=110 and spread>=48 and bright>=.08
                      and saturation>=145 and edge>=.09 and detail>=1000)"""
# User annotated real 885, V41 grayscale metrics logged by independent FFmpeg decode.
# (median,spread,bright,saturation,edge,detail)
POS=[
(144,66.2,.488,57,.084,798.3),(73,59.7,.374,106,.0844,1060.4),
(117,59.3,.45,51,.0859,1003.3),(59,59.1,.295,85,.0788,762.5),
(99,55.5,.256,119,.0797,692.8),(137,58.3,.484,39,.0928,1187.0),
(69,50.8,.105,214,.1175,1288.4),(145,59.1,.488,35,.1001,1097.9),
(134,56.5,.477,50,.1006,1152.2),(56,56.7,.276,105,.0705,733.0)]
NEG=[
(61,61.5,.226,133,.0712,633.3),(56,47.5,.06,122,.068,363.4),
(88,101.9,.456,19,.0741,634.7),(58,48.8,.055,123,.0432,134.6),
(56,48,.054,124,.0338,95),(55,47.6,.049,121,.0329,91.3),
(55,47.7,.041,123,.0378,113.3),(56,48,.046,123,.0353,104.6),
(55,47.4,.036,123,.0366,102.8),(54,45.8,.008,118,.0401,109.1),
(54,46.6,.03,121,.0362,99),(55,44.6,.026,136,.0291,29),
(79,43.5,.132,75,.2164,1035.5),(55,41.9,.004,123,.0437,119),
(103,43.1,.077,126,.0441,95.3)]
KEYS=("median","spread","bright","saturation","edge","detail")
def sha(data):return hashlib.sha256(data).hexdigest()
def prepare():
    old={n:(APP/n).read_bytes() for n in (DETECTOR,BATCH)}
    src=old[DETECTOR].decode("utf-8-sig")
    for before,after in ((OLD_GREY,NEW_GREY),(OLD_RED,NEW_RED)):
        if src.count(before)!=1:raise RuntimeError("CARD_APPEARANCE_EXACT_ANCHOR_MISSING")
        src=src.replace(before,after,1)
    ast.parse(src)
    original=old[DETECTOR]
    use_crlf=b"\r\n" in original
    new_detector=src.encode("utf-8-sig") if original.startswith(b"\xef\xbb\xbf") else src.encode("utf-8")
    if use_crlf:
        new_detector=new_detector.replace(b"\r\n",b"\n").replace(b"\n",b"\r\n")
    old_sha=sha(original)
    new_sha=sha(new_detector)
    batch=old[BATCH]
    code=batch.decode("utf-8-sig")
    if code.count(old_sha)!=1:
        raise RuntimeError("ENGINE_HASH_PIN_NOT_FOUND_OR_AMBIGUOUS")
    code=code.replace(old_sha,new_sha,1)
    ast.parse(code)
    new_batch=code.encode("utf-8-sig") if batch.startswith(b"\xef\xbb\xbf") else code.encode("utf-8")
    if b"\r\n" in batch:
        new_batch=new_batch.replace(b"\r\n",b"\n").replace(b"\n",b"\r\n")
    return old,{DETECTOR:new_detector,BATCH:new_batch}
def checks(after):
    tree=ast.parse(after[DETECTOR].decode("utf-8-sig"))
    fn=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=="verify_popup_cards_v41")
    values={}
    for node in ast.walk(fn):
        if isinstance(node,ast.Assign) and len(node.targets)==1:
            target=node.targets[0]
            if isinstance(target,ast.Name) and target.id in ("grey_card","red_card"):
                values[target.id]=compile(ast.Expression(node.value),"<popup-card>", "eval")
    if sorted(values)!=["grey_card","red_card"]:raise RuntimeError("MISSING_EXACT_GATES")
    def classify(features):
        d=dict(zip(KEYS,features))
        return bool(eval(values["grey_card"],{"__builtins__":{}},d) or
                    eval(values["red_card"],{"__builtins__":{}},d))
    positives=sum(classify(p) for p in POS)
    negatives=sum(classify(n) for n in NEG)
    if positives!=10 or negatives!=0:
        raise RuntimeError(f"REGRESSION_FALSE_POS_OR_NEG_{positives}_OF_10_{negatives}_OF_15")
    # Unchanged critical scan and downstream checks remain present.
    code=after[DETECTOR].decode("utf-8-sig")
    for anchor in ("def popup_candidates(","def scan_popups(","def verified_framed_host_v86(",
                   "suppress_persistent_popup_lookalikes(","NOT_RG_NOTIFICATION_CARD",
                   "FRAMED_HOST_NOT_CONFIRMED_AT_TIMESTAMP"):
        if anchor not in code:raise RuntimeError("SAFETY_GUARD_REMOVED_"+anchor)
    print("RGPOPV92|REAL_EDITOR_LABELED_REGRESSION|TP=10|FN=0|FP=0|TN=15|PASS",flush=True)
    print("RGPOPV92|SCANNER_LAYOUT_QA_GUARDS|UNCHANGED|PASS",flush=True)
def test():
    old,new=prepare()
    checks(new)
    print("RGPOPV92|INTEGRITY_PINS|"+sha(old[DETECTOR])+"|"+sha(new[DETECTOR]),flush=True)
    return old,new
def install():
    old,new=test()
    sys.path.insert(0,str(APP))
    from rg_fullstream_stop_v60 import active_workers
    from rg_fullstream_process_state_v59 import worker_lock_state
    if active_workers() or worker_lock_state(DATA)!="IDLE":
        raise RuntimeError("ACTIVE_FULLSTREAM_WORKER_SAFE_STOP")
    backup=DATA/"RG_REPAIR_BACKUPS"/("RG_POPUP_V92_LABELED_REGRESSION_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:6])
    backup.mkdir(parents=True,exist_ok=False)
    for name,b in old.items():
        (backup/name).write_bytes(b)
        if sha((backup/name).read_bytes())!=sha(b):raise RuntimeError("BACKUP_VERIFICATION_FAIL")
    changed=[]
    try:
        if active_workers() or worker_lock_state(DATA)!="IDLE":
            raise RuntimeError("WORKER_STARTED_AFTER_BACKUP")
        for name in (DETECTOR,BATCH):
            file=APP/name
            if file.read_bytes()!=old[name]:raise RuntimeError("CONCURRENT_PRODUCTION_SOURCE_CHANGE")
            staging=file.with_suffix(".rgpopupv92.tmp")
            staging.write_bytes(new[name])
            if sha(staging.read_bytes())!=sha(new[name]):raise RuntimeError("STAGING_HASH_MISMATCH")
            os.replace(staging,file)
            changed.append(name)
        for name in changed:
            if (APP/name).read_bytes()!=new[name]:raise RuntimeError("POST_INSTALL_HASH_MISMATCH")
        print("RGPOPV92|INSTALLED|PASS|BACKUP|"+str(backup),flush=True)
        print("RGPOPV92|ROLLBACK_FILES|"+",".join(changed),flush=True)
        print("RGPOPV92|NO_VIDEO_OR_QUEUE_STARTED|PASS",flush=True)
    except BaseException:
        for name in reversed(changed):(APP/name).write_bytes(old[name])
        print("RGPOPV92|ROLLBACK|ATTEMPTED",flush=True)
        raise
def main():
    p=argparse.ArgumentParser();p.add_argument("--install",action="store_true")
    a=p.parse_args()
    install() if a.install else test()
if __name__=="__main__":main()
