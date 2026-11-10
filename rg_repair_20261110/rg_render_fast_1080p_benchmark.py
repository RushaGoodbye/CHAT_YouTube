"""1080p throughput-only synthetic benchmark. Nothing edits application or media.
Use 6 seconds at 24fps and eight mostly inactive full-frame popup regions.
"""
import ast,subprocess,sys,time,tempfile
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
FF=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.exe")
def graph(s):
    ns={}
    nodes=[n for n in ast.parse(s).body if isinstance(n,ast.FunctionDef) and n.name in ('_fnum','filter_graph')]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),"<graph>","exec"),ns)
    return ns['filter_graph']
def main():
    from rg_render_fast_v2 import patch
    b=(APP/"rg_fullstream_export_v1.py").read_bytes()
    a=graph(b.decode("utf-8-sig"))
    z=graph(patch(b).decode("utf-8-sig"))
    masks=[{"x":(60+24*i),"y":(80+9*i),"width":220,"height":120,
            "intervals":[(1.2,1.65),(3.1,3.55),(5.2,5.6)]} for i in range(8)]
    p=dict(popup_masks=masks,two_window_intervals=[(.1,5.9)],
           keep=[(0.,6.)],mute=[],audio_offset_seconds=0)
    with tempfile.TemporaryDirectory(prefix="rg_perftest_1080_") as tmp:
        for label,fn in [("BASE",a),("FAST",z)]:
            path=Path(tmp)/(label+".ffscript")
            path.write_text(fn(p),encoding="utf-8")
            cmd=[str(FF),"-hide_banner","-nostdin","-loglevel","error",
                 "-filter_complex_threads","6",
                 "-f","lavfi","-i","testsrc2=size=1920x1080:rate=24:duration=6",
                 "-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=6",
                 "-f","lavfi","-i","testsrc2=size=1920x1080:rate=24:duration=6",
                 "-filter_complex_script",str(path),
                 "-map","[vout]","-map","[aout]","-f","null","-"]
            started=time.perf_counter()
            result=subprocess.run(cmd,capture_output=True,text=True,timeout=125)
            elapsed=time.perf_counter()-started
            if result.returncode:
                raise RuntimeError(label+"_RENDER_FAILED:"+result.stderr[-1400:])
            print("RG1080|"+label+"|SECONDS|"+str(round(elapsed,3)),flush=True)
    print("RG1080|REVIEW|SYNTHETIC_ONLY|VIDEO_NO_QUALITY_CHANGES|LIVE_MEDIA_UNTOUCHED",flush=True)
if __name__=="__main__":main()
