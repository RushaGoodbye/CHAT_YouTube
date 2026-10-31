"""RG 895 V7.11 shadow validation of extended intro search. No writes."""
import ast,hashlib,json,sys,types
from pathlib import Path
APP=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit App')
DATA=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit Data\fullstream_v2\895')
sys.path.insert(0,str(APP))
source=APP/'rg_fullstream_policy_v70.py'
raw=source.read_bytes()
sha=hashlib.sha256(raw).hexdigest()
expected='599e1490590ffd0fda871ed5f94ea772ef7ea75a01aa19c5fdd8fd274c01908f'
print('RGV711|INSTALLED_SOURCE_SHA_MATCH|'+str(sha==expected),flush=True)
if sha!=expected:raise SystemExit('PRODUCTION_SOURCE_DRIFT')
txt=raw.decode('utf-8-sig')
needle='max_search=900, sample_step=.5'
if txt.count(needle)!=1:raise SystemExit('INTRO_SIGNATURE_NOT_UNIQUE')
patched=txt.replace(needle,'max_search=3600, sample_step=.5',1)
ast.parse(patched)
module=types.ModuleType('rg_fullstream_policy_v711_shadow')
module.__file__=str(source)
sys.modules[module.__name__]=module
exec(compile(patched,str(source),'exec'),module.__dict__)
plan=json.loads((DATA/'processing_plan.json').read_text(encoding='utf-8-sig'))
def cb(n,total,t):
 if n%250==0:print('RGV711|INTRO_PROGRESS|'+str(n)+'/'+str(total),flush=True)
start,flags=module.intro_color_host_start(plan['video'],11480.17,progress_callback=cb)
print('RGV711|RESULT|'+json.dumps({'intro':start,'flags':flags},ensure_ascii=True),flush=True)
if start is None or not 909 < float(start) < 920:raise SystemExit('INTRO_SHADOW_RESULT_OUT_OF_RANGE')
if not any('TWO_FRAMES_CONFIRMED' in x for x in flags):raise SystemExit('INTRO_NO_TWO_FRAME_PROOF')
if plan.get('minute_of_silence'):print('RGV711|MINUTE|PROTECTED_RANGES_PRESENT',flush=True)
else:print('RGV711|MINUTE|UNLOCATED_DO_NOT_AUTO_COMMIT_LONG_INTRO_TRIM',flush=True)
print('RGV711|SHADOW_PASS|NO_FILES_MODIFIED',flush=True)
