"""Read-only RG895 popup candidate temporal evidence, metadata only."""
import json,sys,subprocess,math,statistics
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(r'F:\RG_AUTO_EDIT\RG Auto Edit App')))
sys.path.insert(0,str(Path('scripts').resolve()))
import rg_fullstream_detectors_v2 as prod
from rg_fullstream_export_v1 import ffbin
from rg_v711_small_popup_patch import patch_source,verify_sources
import types
p=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit App\rg_fullstream_detectors_v2.py')
before=p.read_bytes()
after=patch_source(before);verify_sources(before,after)
shadow=types.ModuleType('rg_popup_shadow_895');shadow.__file__=str(p);sys.modules[shadow.__name__]=shadow
exec(compile(after,str(p),'exec'),shadow.__dict__)
plan=json.loads(Path(r'F:\RG_AUTO_EDIT\RG Auto Edit Data\fullstream_v2\895\processing_plan.json').read_text(encoding='utf-8-sig'))
source=plan['video']
# Candidate geometry and center timestamps from full 1-second shadow.
candidates=[
 ('p1',1483.3,(575,480,173,66)),
 ('p2',2521.3,(744,508,159,83)),
 ('p3',2657.3,(585,472,150,55)),
 ('p4',2819.3,(744,508,159,94)),
 ('p5',2866.3,(586,472,149,55)),
 ('p6',4166.3,(575,479,173,67)),
 ('p7',7403.3,(775,381,152,70)),
 ('p8',7785.3,(620,384,307,61)),
 ('known_p9',7892.8,(571,509,293,61)),
]
# Each source-seek bounded to avoid OpenCV random access stalls.
def frame(t):
 c=[ffbin('ffmpeg'),'-nostdin','-v','error','-ss',f'{max(0,t):.3f}',
    '-i',source,'-map','0:v:0','-frames:v','1','-pix_fmt','bgr24','-f','rawvideo','pipe:1']
 r=subprocess.run(c,capture_output=True,timeout=14)
 if r.returncode or len(r.stdout)!=1920*1080*3:
  raise RuntimeError('FRAME_BAD_'+str(t)+'_'+str(r.returncode)+'_'+str(len(r.stdout)))
 return np.frombuffer(r.stdout,dtype=np.uint8).reshape(1080,1920,3).copy()
def overlap(a,b):
 x=max(0,min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0]))
 y=max(0,min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1]))
 return x*y/max(1,min(a[2]*a[3],b[2]*b[3]))
summary=[]
for key,t,rect in candidates:
 # Previous shadow indicates candidate onset t; sample before and 0–7 seconds after.
 times=[t-3,t-1,t,t+.5,t+1,t+2,t+3,t+5,t+7,t+12]
 infos=[];f0=None
 x,y,w,h=rect
 x0=max(0,x-10);y0=max(0,y-8);x1=min(1920,x+w+10);y1=min(1080,y+h+8)
 for i,ts in enumerate(times):
  im=frame(ts)
  if f0 is None:f0=im
  layout='dual' if prod.verified_host(im) else ('solo' if prod.verified_single_host(im) else None)
  region=prod.popup_search_area(layout) if layout else None
  orig=prod.popup_candidates(im,region) if region else []
  patch=shadow.popup_candidates(im,region) if region else []
  hit=max([overlap(rect,r) for r in patch],default=0)
  baseline=max([overlap(rect,r) for r in orig],default=0)
  delta=np.mean(np.abs(im[y0:y1,x0:x1].astype(np.int16)-f0[y0:y1,x0:x1].astype(np.int16)))
  # global motion reference for distinguishing fullscreen scene changes
  ref=np.mean(np.abs(im[100:270,70:400].astype(np.int16)-f0[100:270,70:400].astype(np.int16)))
  infos.append({'dt':round(ts-t,2),'old':round(baseline,2),'new':round(hit,2),'roi_change':round(float(delta),1),'reference_change':round(float(ref),1),'layout':layout})
 count=sum(j['new']>.35 for j in infos)
 s={'candidate':key,'t':round(t,2),'box':rect,'hit_count':count,'frames':infos}
 summary.append(s)
 print('RGTEMP|CANDIDATE|'+json.dumps(s,separators=(',',':')),flush=True)
print('RGTEMP|SUMMARY|'+json.dumps({'tested':len(summary),'candidates_with_two_hits':sum(z['hit_count']>=2 for z in summary),'no_media_upload':True,'read_only':True}),flush=True)
