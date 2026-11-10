"""Compare FFmpeg filter_complex_threads without changing encoder or source.
Synthetic 1080p graph only, no production modifications.
"""
import ast,subprocess,sys,time,tempfile
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
FF=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.exe")
def load(s):
    tree=ast.parse(s)
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ("_fnum","filter_graph")]
    ns={};exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),"<graph>","exec"),ns)
    return ns["filter_graph"]
def run():
    from rg_render_fast_v2 import patch
    orig=(APP/"rg_fullstream_export_v1.py").read_bytes()
    fn=load(patch(orig).decode("utf-8-sig"))
    cfg={"popup_masks":[{"x":50+19*i,"y":90+7*i,"width":220,"height":120,
         "intervals":[(.8,1.25),(2.8,3.25),(4.2,4.65)]} for i in range(8)],
         "two_window_intervals":[(.1,5.9)],"keep":[(0.,6.)],
         "mute":[],"audio_offset_seconds":0}
    with tempfile.TemporaryDirectory(prefix="rg_thread_tune_") as tmp:
        filterfile=Path(tmp)/"filter.ffscript"
        filterfile.write_text(fn(cfg),encoding="utf-8")
        data=[]
        for threads in (None,4,8,12,16):
            args=[str(FF),"-hide_banner","-nostdin","-loglevel","error"]
            if threads is not None:args+=["-filter_complex_threads",str(threads)]
            args+=["-f","lavfi","-i","testsrc2=size=1920x1080:rate=24:duration=6",
                "-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=6",
                "-f","lavfi","-i","testsrc2=size=1920x1080:rate=24:duration=6",
                "-filter_complex_script",str(filterfile),
                "-map","[vout]","-map","[aout]","-f","null","-"]
            st=time.perf_counter()
            p=subprocess.run(args,capture_output=True,text=True,timeout=120)
            elapsed=time.perf_counter()-st
            if p.returncode:raise RuntimeError("THREADS_"+str(threads)+":"+p.stderr[-900:])
            data.append((threads,round(elapsed,3)))
            print("RGTHREAD|THREADS|"+("DEFAULT" if threads is None else str(threads))+"|SECONDS|"+str(round(elapsed,3)),flush=True)
        winner=min(data,key=lambda x:x[1])
        print("RGTHREAD|FASTEST_SAMPLE|"+str(winner),flush=True)
        print("RGTHREAD|NO_PRODUCTION_MEDIA_OR_CODE_CHANGED|PASS",flush=True)
if __name__=="__main__":run()
