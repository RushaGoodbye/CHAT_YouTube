"""RG 895 read-only forensic audit; metadata only, does not print transcript/video/paths."""
import json
import math
import os
import subprocess
from pathlib import Path

S='895'
APP=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit App')
DATA=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit Data')
P=DATA/'fullstream_v2'/S
OUT=APP/S/'FULLSTREAM_YOUTUBE'/f'RG_{S}_FULL_YOUTUBE_REVIEW.mp4'
REP=OUT.with_suffix('.json')

def row(k,v):
    if isinstance(v,(dict,list)):
        v=json.dumps(v,ensure_ascii=True,separators=(',',':'))
    print('RG895AUDIT|'+k+'|'+str(v)[:1000],flush=True)

def read(path):
    if not path.is_file():
        row('MISSING',path.name)
        return {}
    try:
        obj=json.loads(path.read_text(encoding='utf-8-sig'))
        if isinstance(obj,dict):return obj
        row('INVALID_OBJECT',path.name)
    except Exception as e:row('PARSE_FAILED',path.name+':'+type(e).__name__)
    return {}

def array(o,k):
    v=o.get(k)
    return v if isinstance(v,list) else []

def intervals_duration(a):
    total=0
    for x in a:
        try:
            if isinstance(x,dict):
                start=x['start'];end=x['end']
            else:start,end=x[:2]
            total+=max(0,float(end)-float(start))
        except Exception:continue
    return round(total,2)

def popup_sec(items):
    return round(sum(intervals_duration(x.get('intervals',[])) for x in items if isinstance(x,dict)),2)

def safe_flags(obj):
    flags=obj if isinstance(obj,list) else []
    return [str(x)[:110] for x in flags if isinstance(x,str)][:60]

def main():
    row('START','READ_ONLY_NO_MEDIA_UPLOAD_NO_CHANGES')
    for x in (OUT,REP,P/'processing_plan.json',P/'preflight.json',P/'status.json',P/'plan.json'):
        row('FILE_'+x.name,{'exists':x.is_file(),'bytes':x.stat().st_size if x.is_file() else 0})
    stage=read(P/'stage_state_v52.json')
    row('STAGE_STATE',{k:stage.get(k) for k in ('stage','detail','state','updated_at','finished_at','percent') if k in stage})
    stat=read(P/'status.json')
    row('STATUS',{k:stat.get(k) for k in ('state','stage','technical_render_ok','publish_ready') if k in stat})
    pl=read(P/'processing_plan.json')
    row('PLAN_COUNTS',{
        'asr_word_count':len(array(pl,'transcribed_words')),
        'popup_mask_count':len(array(pl,'popup_masks')),
        'popup_interval_seconds':popup_sec(array(pl,'popup_masks')),
        'two_window_ranges':len(array(pl,'two_window_intervals')),
        'two_window_seconds':intervals_duration(array(pl,'two_window_intervals')),
        'underlay_file_present':bool(pl.get('underlay_path')) and Path(pl['underlay_path']).is_file(),
        'intro_trim_seconds':pl.get('intro_trim_seconds'),
        'dialogue_ranges_count':len(array(pl,'dialogue_ranges')),
        'dialogue_gap_cuts_count':len(array(pl,'dialogue_gap_cuts')),
        'minute_ranges_count':len(array(pl,'minute_of_silence')),
        'fullstream_object_blur_disabled':pl.get('fullstream_object_blur_disabled'),
        'manual_mutes_count':len(array(pl,'manual_mutes')),
        'asr_failed':pl.get('asr_failed'),
        'popup_coverage_verified':pl.get('popup_coverage_verified'),
        'transcript_double_checked':pl.get('transcript_double_checked'),
    })
    row('PLAN_FLAGS',safe_flags(pl.get('extra_review_flags')))
    rep=read(REP)
    if rep:
        summary={k:rep.get(k) for k in (
            'status','technical_render_ok','content_qa_status','censored_intervals',
            'cut_intervals','intro_trim_seconds','audio_alignment_verified',
            'minute_of_silence_preserved','censorship_applied','popup_blur_applied',
            'underlay_applied','underlay_two_window_seconds','duration_seconds',
            'expected_duration_seconds','audio_packet_count','publish_ready',
        )}
        row('EXPORT_REPORT',summary)
        row('EXPORT_PROTECTION_EVIDENCE',rep.get('protection_evidence') or {})
        row('EXPORT_CENSOR_QUALITY',rep.get('censor_quality') or {})
        row('EXPORT_QA',rep.get('content_qa_v65') or {})
        row('EXPORT_FLAGS',safe_flags(rep.get('review_flags')))
        row('EXPORT_REJECTED_CUT_COUNT',len(array(rep,'rejected_cuts')))
    if OUT.is_file():
        ffprobe=Path(r'F:\RG_AUTO_EDIT\RG Auto Edit Runtime\ffmpeg\bin\ffprobe.exe')
        if ffprobe.is_file():
            try:
                cmd=[str(ffprobe),'-v','error','-show_entries',
                     'format=duration,size:stream=codec_type,codec_name,width,height',
                     '-of','json',str(OUT)]
                result=subprocess.run(cmd,capture_output=True,text=True,timeout=90)
                j=json.loads(result.stdout) if result.returncode==0 else {}
                row('PHYSICAL_MEDIA',{
                    'duration':j.get('format',{}).get('duration'),
                    'size':j.get('format',{}).get('size'),
                    'streams':j.get('streams',[])[:4],
                    'ffprobe_ok':result.returncode==0})
            except Exception as e:row('FFPROBE_EXCEPTION',type(e).__name__)
    row('END','AUDIT_COMPLETE_NO_FILES_MODIFIED')

if __name__=='__main__':main()