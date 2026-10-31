"""Read-only physical spot audit for RG895. No writes, uploads, transcription, or full video scan."""
from pathlib import Path
import json, os, subprocess, math, statistics, sys, array

APP=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit App')
DATA=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit Data')
ROOT=DATA/'fullstream_v2'/'895'
REPORT=APP/'895'/'FULLSTREAM_YOUTUBE'/'RG_895_FULL_YOUTUBE_REVIEW.json'
PROBE='RG895PHYSICAL'
BIN=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit Runtime\ffmpeg\bin\ffmpeg.exe')

def log(k,v):
    print(PROBE+'|'+k+'|'+json.dumps(v,ensure_ascii=True,separators=(',',':')),flush=True)

def get_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def exec_bytes(args, max_seconds=35):
    try:
        c=subprocess.run([str(BIN),'-hide_banner','-nostdin','-loglevel','error',*args],
                         capture_output=True,timeout=max_seconds)
        if c.returncode: return None,'FFMPEG_EXIT_'+str(c.returncode)
        return c.stdout,None
    except subprocess.TimeoutExpired:
        return None,'TIMED_OUT'
    except Exception as e:
        return None,type(e).__name__

def rms_at(path,t):
    if t<0: return None,'INVALID_TIME'
    buf,error=exec_bytes(['-ss',f'{t:.4f}','-i',str(path),'-t','0.14','-vn',
                         '-ac','1','-ar','8000','-f','f32le','pipe:1'])
    if error:return None,error
    if not buf or len(buf)<1024:return None,'EMPTY_AUDIO'
    a=array.array('f');a.frombytes(buf[:len(buf)//4*4]);
    if not a:return None,'NO_SAMPLES'
    return math.sqrt(sum(min(100,abs(x))**2 for x in a)/len(a)),None

def pcm_clips(ref,output,ranges):
    selected=[]
    for a,b in ranges:
        a,b=float(a),float(b)
        if b-a>=0.4 and b>1:
            t=(a+b)/2
            if all(abs(t-q)>120 for q in selected):selected.append(t)
        if len(selected)>=6:break
    result=[]
    for t in selected:
        x,e=rms_at(ref,t);y,f=rms_at(output,t)
        result.append({'t':round(t,2),'source_rms':round(x,6) if x is not None else None,
                       'output_rms':round(y,6) if y is not None else None,
                       'ratio':round(y/x,5) if y is not None and x is not None and x>0.00001 else None,
                       'error':e or f})
    return result

def mono_frame(video,t,box):
    x,y,w,h=[int(a) for a in box]
    if min(x,y)<0 or w<6 or h<6 or x+w>1920 or y+h>1080:return None,'BAD_BOX'
    payload,err=exec_bytes(['-ss',f'{t:.4f}','-i',str(video),'-frames:v','1',
                            '-vf',f'crop={w}:{h}:{x}:{y},format=gray','-f','rawvideo','pipe:1'])
    if err:return None,err
    if not payload or len(payload)!=w*h:return None,'BAD_FRAME_SIZE'
    return payload,None

def frame_stats(a,b,w,h):
    # absolute delta between decoded source and output; a purely technical metric,
    # not evidence of complete underlay or popup coverage.
    sampled_delta=sum(abs(a[i]-b[i]) for i in range(0,len(a),4))
    diff=sampled_delta/max(1,len(range(0,len(a),4)))
    def edge(p):
        steps=0;val=0
        for y in range(0,h,4):
            for x in range(0,w-4,4):
                i=y*w+x
                val+=abs(p[i]-p[i+4]);steps+=1
        return val/max(1,steps)
    es=edge(a);eo=edge(b)
    return {'mean_abs_diff':round(diff,2),'source_edge':round(es,2),'output_edge':round(eo,2),
            'edge_ratio':round(eo/es,3) if es>1 else None}

def frame_comparison(source,output,t,box):
    a,e=mono_frame(source,t,box)
    b,f=mono_frame(output,t,box)
    if a is None or b is None:return {'t':round(t,2),'error':e or f}
    return {'t':round(t,2),**frame_stats(a,b,int(box[2]),int(box[3]))}

def midpoint(l):
    if isinstance(l,dict):
        l=l.get('intervals',[])
    for r in l:
        try:
            a,b=(r['start'],r['end']) if isinstance(r,dict) else r[:2]
            if b-a>=1.0:return (a+b)/2
        except (ValueError,TypeError,KeyError):continue
    return None

def main():
    log('START','READ_ONLY_PHYSICAL_SPOT_CHECK')
    if not BIN.is_file():return log('ERROR','FFMPEG_NOT_FOUND')
    report=get_json(REPORT)
    plan=get_json(ROOT/'processing_plan.json')
    out=Path(report['output']);video=Path(report['source_video']);audio=Path(report['separate_audio'])
    log('INPUTS_PRESENT',{'output':out.is_file(),'source_video':video.is_file(),
                          'source_audio':audio.is_file(),'plan':True,'ffmpeg':True})
    if not all(x.is_file() for x in (out,video,audio)):return log('STOP','SOURCE_UNAVAILABLE')
    sys.path.insert(0,str(APP))
    try:
        from rg_fullstream_quality_v3 import classify_words_v3
        mutes,reviews=classify_words_v3(plan.get('transcribed_words',[]))
        log('MUTE_SOURCE',{'interv':len(mutes),'plan_words':len(plan.get('transcribed_words',[]))})
        logs=pcm_clips(audio,out,mutes)
        log('PHYSICAL_MUTE_SAMPLE',logs)
    except Exception as e:
        log('MUTE_ERROR',type(e).__name__+':'+str(e)[:100])
    pop=[]
    for mask in plan.get('popup_masks',[])[:3]:
        if not isinstance(mask,dict):continue
        t=midpoint(mask.get('intervals',[]))
        if t is None:continue
        box=[mask.get('x',0),mask.get('y',0),mask.get('width',0),mask.get('height',0)]
        pop.append(frame_comparison(video,out,t,box))
    log('PHYSICAL_POPUP_SAMPLE',pop)
    two=report.get('underlay_two_window_intervals') or plan.get('two_window_intervals') or []
    checks=[]
    candidates=[]
    for arr in (two[:1],two[len(two)//2:len(two)//2+1],two[-1:]):
        t=midpoint(arr)
        if t is not None:candidates.append(('two_window',t))
    for t in (400.0,5500.0,11200.0):
        if not any(float(a)<=t<=float(b) for a,b in two):candidates.append(('outside_two_window',t))
    for tag,t in candidates[:6]:
        r=frame_comparison(video,out,t,[40,730,280,140]);r['segment']=tag;checks.append(r)
    log('PHYSICAL_UNDERLAY_SAMPLE',checks)
    log('INTRO',{'trim':report.get('intro_trim_seconds'),
                 'verified':report.get('intro_host_color_verified')})
    log('END','READ_ONLY_COMPLETE')

if __name__=='__main__':main()