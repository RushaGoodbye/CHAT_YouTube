"""A/B test current versus timeline-gated popup Gaussian blur.
No access to real user media, no GPU video encoding, no working app changes.
"""
import ast,sys,subprocess,tempfile,time,hashlib,json,statistics
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
FF=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.exe")
def load_graph(source):
    tree=ast.parse(source)
    funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ("filter_graph","_fnum")]
    assert len(funcs)==2
    minimal=ast.Module(body=funcs,type_ignores=[])
    x={}
    exec(compile(ast.fix_missing_locations(minimal),"<filter-equivalence>","exec"),x)
    return x["filter_graph"]
def run():
    sys.path.insert(0,str(APP))
    from rg_fast_popup_gblur_v1 import patched
    original=(APP/"rg_fullstream_export_v1.py").read_bytes()
    old=load_graph(original.decode("utf-8-sig"))
    new=load_graph(patched(original).decode("utf-8-sig"))
    masks=[
        {"x":60+i*22,"y":80+i*9,"width":190,"height":110,
         "intervals":[(0.8,1.55),(2.4,3.0)]}
        for i in range(6)
    ]
    job={"popup_masks":masks,"two_window_intervals":[],
         "keep":[(0.,4.)],"mute":[],"audio_offset_seconds":0}
    a=old(job);b=new(job)
    assert a!=b and a.count("gblur=sigma=15:steps=2")==6
    assert b.count("gblur=sigma=15:steps=2:enable=")==6
    print("RGPIX|FILTERS|6|TIME_RANGES|2",flush=True)
    outputs={}
    with tempfile.TemporaryDirectory(prefix="rg_fast_gblur_") as tmp:
        for label,graph in (("BASELINE",a),("OPTIMIZED",b)):
            filt=Path(tmp)/(label+".ffscript")
            filt.write_text(graph,encoding="utf-8")
            cmd=[str(FF),"-hide_banner","-nostdin","-loglevel","error",
                 "-f","lavfi","-i","testsrc2=size=960x540:rate=8:duration=4",
                 "-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=4",
                 "-filter_complex_script",str(filt),"-map","[vout]","-map","[aout]",
                 "-f","framemd5","-"]
            stamp=time.perf_counter()
            p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",timeout=100)
            elapsed=time.perf_counter()-stamp
            if p.returncode:raise RuntimeError(label+"_FFMPEG_FAILED:"+p.stderr[-1100:])
            # Include raw per-frame output checksums; strip commentary / ffmpeg versions.
            lines=[line.strip() for line in p.stdout.splitlines() if line and not line.startswith("#")]
            assert len(lines)>20,(label,len(lines))
            outputs[label]=lines
            print("RGPIX|"+label+"|ELAPSED_SECONDS|"+str(round(elapsed,3))+"|PACKETS|"+str(len(lines)),flush=True)
        if outputs["BASELINE"]!=outputs["OPTIMIZED"]:
            import itertools
            differences=list(itertools.islice(((i,x,y) for i,(x,y) in
                enumerate(zip(outputs["BASELINE"],outputs["OPTIMIZED"])) if x!=y),0,5))
            raise RuntimeError("FRAME_OR_AUDIO_HASH_DIFFERENCE:"+repr(differences))
        print("RGPIX|PIXEL_AND_AUDIO_HASH_EQUIVALENCE|PASS",flush=True)
        print("RGPIX|VIDEO_TIMESTAMPS_EQUAL|PASS",flush=True)
        print("RGPIX|PRODUCTION_APP_OR_MEDIA_CHANGED|FALSE",flush=True)
if __name__=="__main__":run()
