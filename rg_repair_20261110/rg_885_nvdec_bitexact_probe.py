"""Compare bitexact decoded HEVC source frames CPU vs NVDEC, read-only.
Uses a 2-second input sample; no transcoded output written.
"""
import subprocess,time
from pathlib import Path
FF=Path(r"C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.exe")
SOURCE=Path(r"\\AlexLosServer\Work\WORK\RUSHA GOODBYE\Раша GOODBYE\ГОТОВО\ЗАПИСИ СТРИМОВ\RushaGoodbye - Live\RushaGoodbye - Live\885.mp4")
def run():
    if not SOURCE.is_file():raise RuntimeError("SOURCE_MISSING")
    result={}
    for name,decoder in (("CPU",[]),("NVDEC",["-hwaccel","cuda"])):
        cmd=[str(FF),"-hide_banner","-nostdin","-loglevel","error"]+decoder+[
             "-ss","00:03:00","-i",str(SOURCE),"-t","2","-map","0:v:0",
             "-an","-sn","-pix_fmt","yuv420p","-f","framemd5","-"]
        start=time.perf_counter()
        r=subprocess.run(cmd,text=True,capture_output=True,timeout=85)
        elapsed=time.perf_counter()-start
        if r.returncode:raise RuntimeError(name+"_FAILED:"+r.stderr[-1000:])
        lines=[x.strip() for x in r.stdout.splitlines() if x and not x.startswith("#")]
        if len(lines)!=60:raise RuntimeError(name+"_FRAME_COUNT_"+str(len(lines)))
        result[name]=lines
        print("RGDEC|"+name+"|DECODE_SECONDS|"+str(round(elapsed,3))+"|FRAMES|"+str(len(lines)),flush=True)
    if result["CPU"]!=result["NVDEC"]:
        diffs=sum(a!=b for a,b in zip(result["CPU"],result["NVDEC"]))
        print("RGDEC|FRAME_HASH_DIFFERENCES|"+str(diffs)+"|NVDEC_NOT_QUALIFIED",flush=True)
    else:print("RGDEC|PIXEL_AND_PTS_IDENTICAL|PASS",flush=True)
    print("RGDEC|NO_MEDIA_OR_APP_CHANGES|PASS",flush=True)
if __name__=="__main__":run()
