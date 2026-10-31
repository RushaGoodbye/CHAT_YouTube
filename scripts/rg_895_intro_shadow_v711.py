"""Read-only first-host intro detector shadow; no media upload or edits."""
import json,math,sys
from pathlib import Path
import cv2,numpy as np
APP=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit App')
DATA=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit Data\fullstream_v2\895')
sys.path.insert(0,str(APP))
from rg_fullstream_detectors_v2 import verified_host,verified_single_host
from rg_fullstream_policy_v70 import _color_host

def emit(k,v):print('RG895INTRO|'+k+'|'+json.dumps(v,ensure_ascii=True,default=str),flush=True)
plan=json.loads((DATA/'processing_plan.json').read_text(encoding='utf-8-sig'))
cap=cv2.VideoCapture(plan['video'])
if not cap.isOpened():raise SystemExit('SOURCE_OPEN_FAILED')
checks=[]
try:
 for t in [0,.3,.6,1,2,3,4,5,6,7,8,9,10,12,15,18,20,25,30,40,50,60,90,120,180,240,300,420,600,750,890]:
  cap.set(cv2.CAP_PROP_POS_MSEC,t*1000)
  ok,im=cap.read()
  if not ok or im is None:continue
  host=bool(verified_host(im));solo=bool(verified_single_host(im))
  thumb=im[120:650:6,135:835:6]
  hsv=cv2.cvtColor(thumb,cv2.COLOR_BGR2HSV)
  sat=float(np.mean((hsv[:,:,1]>43)&(hsv[:,:,2]>40)))
  contrast=float(np.std(thumb))
  face=bool(_color_host(im)) if host or solo else False
  checks.append({'t':t,'host':host,'solo':solo,'sat':round(sat,3),'contrast':round(contrast,1),'face':face})
finally:cap.release()
emit('SAMPLES',checks)
emit('SUMMARY',{'n':len(checks),'first_layout':next((c['t'] for c in checks if c['host'] or c['solo']),None),
  'first_layout_color':next((c['t'] for c in checks if (c['host'] or c['solo']) and c['sat']>.09),None),
  'first_face':next((c['t'] for c in checks if c['face']),None),
  'number_face':sum(c['face'] for c in checks),
  'color_layout_count':sum((c['host'] or c['solo']) and c['sat']>.09 for c in checks)})