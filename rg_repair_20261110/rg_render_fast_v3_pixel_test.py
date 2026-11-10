"""Exact end-to-end FFmpeg pixel/audio hashes with real 1920x1080 underlay shape,
frame-identical popup masks, 2 active regions, 3-second synthetic source.
Does not touch real media/production worker.
"""
import sys,ast,subprocess,tempfile,time
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
FF=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.exe")
def graph(src):
    funcs=[x for x in ast.parse(src).body if isinstance(x,ast.FunctionDef) and x.name in ('_fnum','filter_graph')]
    assert len(funcs)==2
    ns={}
    exec(compile(ast.fix_missing_locations(ast.Module(body=funcs,type_ignores=[])),'<graph>','exec'),ns)
    return ns['filter_graph']
def test():
    sys.path.insert(0,str(Path(__file__).parent))
    from rg_render_fast_v3 import patch
    original=(APP/"rg_fullstream_export_v1.py").read_bytes()
    before=graph(original.decode("utf-8-sig"))
    after=graph(patch(original).decode("utf-8-sig"))
    p={"popup_masks":[
       {"x":54,"y":40,"width":190,"height":110,"intervals":[(.4,1.15),(1.7,2.3)]},
       {"x":360,"y":440,"width":155,"height":95,"intervals":[(.85,1.55)]}],
       "two_window_intervals":[(.2,2.15)],
       "keep":[(0.,3.)],"mute":[],"audio_offset_seconds":0}
    graphs={"BEFORE":before(p),"AFTER":after(p)}
    if "trim=end_frame=1" not in graphs["AFTER"]:raise RuntimeError("MASK_NOT_OPTIMIZED")
    with tempfile.TemporaryDirectory(prefix="rg_filter_v2_equal_") as tmp:
        hashes={}
        for name,g in graphs.items():
            f=Path(tmp)/(name+".ffscript")
            f.write_text(g,encoding="utf-8")
            cmd=[str(FF),"-hide_banner","-nostdin","-loglevel","error"]+ (["-filter_complex_threads","8"] if name=="AFTER" else []) + [
                "-f","lavfi","-i","testsrc2=size=1920x1080:rate=5:duration=3",
                "-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=3",
                "-f","lavfi","-i","testsrc2=size=1920x1080:rate=5:duration=3",
                "-filter_complex_script",str(f),"-map","[vout]","-map","[aout]",
                "-f","framemd5","-"]
            start=time.perf_counter()
            result=subprocess.run(cmd,text=True,capture_output=True,encoding="utf-8",timeout=120)
            secs=time.perf_counter()-start
            if result.returncode:
                raise RuntimeError(name+"_FFMPEG_FAILED:"+result.stderr[-1800:])
            raw=[line.strip() for line in result.stdout.splitlines() if line and not line.startswith("#")]
            if len(raw)<15:raise RuntimeError("TOO_FEW_PACKETS_"+name)
            hashes[name]=raw
            print("RGFRAME|"+name+"|SECONDS|"+str(round(secs,3))+"|PACKETS|"+str(len(raw)),flush=True)
        if hashes["BEFORE"]!=hashes["AFTER"]:
            diffs=[]
            for i,(a,b) in enumerate(zip(hashes["BEFORE"],hashes["AFTER"])):
                if a!=b:diffs.append((i,a,b))
                if len(diffs)>=4:break
            raise RuntimeError("PIXEL_DIFFERENCE:"+repr(diffs))
        print("RGFRAME|UNDERLAY_POPUP_AUDIO_FULL_HASH_IDENTICAL|PASS",flush=True)
        print("RGFRAME|NO_PRODUCTION_CHANGES|PASS",flush=True)
if __name__=="__main__":test()
