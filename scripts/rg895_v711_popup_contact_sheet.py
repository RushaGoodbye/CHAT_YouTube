"""Build one local contact sheet for manual popup mask adjudication. Source read-only.
No image is uploaded to GitHub or printed into workflow logs.
"""
from pathlib import Path
import json,subprocess,hashlib,sys
import numpy as np
import cv2
APP=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit App')
sys.path.insert(0,str(APP))
from rg_fullstream_export_v1 import ffbin
PLAN=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit Data\fullstream_v2\895\processing_plan.json')
OUTPUT=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit Data\fullstream_v2\895\QA_V711\RG895_POPUP_CONTACT_SHEET_V711.png')
ROWS=[
 ("01",1483.3,(575,480,173,66)),
 ("02",2521.3,(744,508,159,83)),
 ("03",2657.3,(585,472,150,55)),
 ("04",2819.3,(744,508,159,94)),
 ("05",2866.3,(586,472,149,55)),
 ("06",4166.3,(575,479,173,67)),
 ("07",7403.3,(775,381,152,70)),
 ("08",7785.3,(620,384,307,61)),
 ("09",7892.8,(571,509,293,61)),
]
plan=json.loads(PLAN.read_text(encoding='utf-8-sig'))
src=plan['video']
def one(t):
 cmd=[ffbin('ffmpeg'),'-hide_banner','-nostdin','-v','error','-ss',str(max(0,t)),
      '-i',src,'-map','0:v:0','-frames:v','1','-pix_fmt','bgr24','-f','rawvideo','pipe:1']
 p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=18)
 if p.returncode or len(p.stdout)!=1920*1080*3:
  raise RuntimeError('FRAME_NOT_READ_AT_'+str(t))
 return np.frombuffer(p.stdout,dtype=np.uint8).reshape(1080,1920,3)
tilew,tileh=465,258
sheet=np.full((tileh*len(ROWS),tilew*3,3),30,dtype=np.uint8)
for ri,(key,t,box) in enumerate(ROWS):
 x,y,w,h=box
 # Give the region enough surroundings to distinguish a pop-up from a
 # broadcast decoration or changing entire-screen graphic.
 cropx=max(0,x-115);cropy=max(0,y-115)
 cropw=min(1920-cropx,max(450,w+230));croph=min(1080-cropy,max(245,h+235))
 for col,(dt,label) in enumerate([(-2.0,'BEFORE'),(2.0,'DURING'),(11.0,'AFTER')]):
  im=one(t+dt)[cropy:cropy+croph,cropx:cropx+cropw].copy()
  if col==1:
   cv2.rectangle(im,(x-cropx,y-cropy),(x+w-cropx,y+h-cropy),(0,220,255),3)
  resized=cv2.resize(im,(tilew,tileh-39),interpolation=cv2.INTER_AREA)
  y0=ri*tileh;x0=col*tilew
  sheet[y0:y0+tileh-39,x0:x0+tilew]=resized
  cv2.putText(sheet,f'{key} {label} {t+dt:.1f}s',(x0+9,y0+tileh-11),
              cv2.FONT_HERSHEY_SIMPLEX,0.6,(240,240,240),1,cv2.LINE_AA)
OUTPUT.parent.mkdir(parents=True,exist_ok=True)
if not cv2.imwrite(str(OUTPUT),sheet):
 raise RuntimeError('CONTACT_SHEET_SAVE_FAILED')
assert OUTPUT.is_file() and OUTPUT.stat().st_size>50000
print('RGSHEET|CREATED|'+str(OUTPUT),flush=True)
print('RGSHEET|METADATA|'+json.dumps({'rows':len(ROWS),'columns':3,'width':sheet.shape[1],
 'height':sheet.shape[0],'bytes':OUTPUT.stat().st_size,
 'sha256':hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),'original_media_untouched':True}),flush=True)
