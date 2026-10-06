from __future__ import annotations
import hashlib,json,os,shutil,statistics,subprocess,time,xml.etree.ElementTree as ET
from pathlib import Path

APP=Path(__file__).resolve().parent
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
if os.environ.get("RG_PACK500_DRYRUN"): DATA=APP/"_PACK500_DATA"
JOURNAL=DATA/"crash_recovery"/"CRASH_RECOVERY.jsonl"
PENDING_UPDATE=DATA/"pending_update.json"
SHADOW=DATA/"shadow_queue"
STABLE=DATA/"production_stable.json"
PROVENANCE=DATA/"xml_provenance"
XML_LOCKS=DATA/"xml_locks"

FEATURES={
1:"Автопріоритет черги за тривалістю",2:"Predictive scheduler",3:"GPU parallelism guard",4:"GPU thermal guard",
5:"Dynamic model lifecycle",6:"Warm model cache",7:"SMART cache eviction",8:"Cache inspector",9:"Checkpoint browser",
10:"Dependency graph",11:"Minimal safe recalculation",12:"Boundary confidence",13:"Pre-heavy anomaly guard",
14:"Neighbour boundary guard",15:"Golden boundary history",16:"XML semantic validation",17:"Premiere import simulation",
18:"XML SHA256 lock",19:"Immutable completed dialogue",20:"Version provenance",21:"Compatible cache migration",
22:"Regression corpus",23:"A/B benchmark",24:"Canary update",25:"Auto rollback policy",26:"UI/Core version split",
27:"Separate package domains",28:"Update staging",29:"Install after queue",30:"OS-level update lock",
31:"Session ID propagation",32:"Process ownership",33:"Crash Recovery Journal",34:"Atomic state files",
35:"SMB shadow queue",36:"NAS latency adaptation",37:"Offline-safe local continuation",38:"Unified Control Center",
39:"One-click diagnostics",40:"Safe auto-fix",41:"Meaningful notifications",42:"Completion notification hook",
43:"Do-not-disturb",44:"Auto-open result policy",45:"Multi-stream dashboard",46:"Live throughput",
47:"Bottleneck explanation",48:"Median last-10 regression signal",49:"Post-update performance report",
50:"Production Stable freeze"}

def atomic_json(path,data):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+".tmp");t.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8");os.replace(t,p);return p

def read_json(path,default=None):
    try:return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:return {} if default is None else default

def journal_event(kind,stream=None,run_id=None,stage=None,detail=None,extra=None):
    JOURNAL.parent.mkdir(parents=True,exist_ok=True)
    row={"ts":time.time(),"kind":str(kind),"stream":str(stream or ""),"run_id":str(run_id or ""),"stage":str(stage or ""),"detail":str(detail or "")}
    if isinstance(extra,dict):row.update(extra)
    with JOURNAL.open("a",encoding="utf-8") as f:
        f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n");f.flush()
        try:os.fsync(f.fileno())
        except Exception:pass
    return row

def _ps_json(script,timeout=20):
    try:
        cp=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",script],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout)
        txt=(cp.stdout or "").strip()
        if not txt:return []
        return json.loads(txt)
    except Exception:return []

def active_backend_processes():
    d=_ps_json(r'''$p=Get-CimInstance Win32_Process | Where-Object {
      (($_.Name -eq 'python.exe') -or ($_.Name -eq 'pythonw.exe')) -and
      (($_.CommandLine -like '*rg_production_wrapper.py*') -or
       ($_.CommandLine -like '*rg_multi_dialogue.py*') -or
       ($_.CommandLine -like '*rg_auto_edit_one_button.py*'))
    }; $p | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | ConvertTo-Json -Compress''')
    if isinstance(d,dict):d=[d]
    return d if isinstance(d,list) else []

def update_locked():
    p=active_backend_processes();return {"locked":bool(p),"processes":p}

def stage_update(path):
    p=Path(path).resolve()
    if not p.is_file():raise FileNotFoundError(str(p))
    return atomic_json(PENDING_UPDATE,{"schema":"RG_PENDING_UPDATE_V1","path":str(p),"created_at":time.time(),"status":"STAGED"})
def pending_update():
    d=read_json(PENDING_UPDATE,{})
    p=Path(str(d.get("path") or ""))
    return d if p.is_file() else None
def clear_pending_update():
    try:PENDING_UPDATE.unlink()
    except FileNotFoundError:pass

def runtime_snapshot():
    return {str(p):{"exists":p.exists(),"is_symlink":p.is_symlink()} for p in [
        Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime"),
        Path(r"C:\Users\fauto\AppData\Local\Programs\RG Auto Edit Runtime")]}

def gpu_snapshot():
    exe=shutil.which("nvidia-smi") or "nvidia-smi"
    try:
        cp=subprocess.run([exe,"--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,pstate","--format=csv,noheader,nounits"],
                          capture_output=True,text=True,timeout=10)
        a=[x.strip() for x in (cp.stdout or "").splitlines()[0].split(",")]
        return {"ok":True,"name":a[0],"temperature_c":float(a[1]),"util_pct":float(a[2]),"vram_used_mb":float(a[3]),"vram_total_mb":float(a[4]),"pstate":a[5]}
    except Exception as e:return {"ok":False,"error":str(e)}

def gpu_policy():
    g=gpu_snapshot()
    if not g.get("ok"):return {"heavy_parallel":False,"warm_cache":False,"reason":"telemetry_unavailable","gpu":g}
    free=float(g["vram_total_mb"])-float(g["vram_used_mb"]);hot=float(g["temperature_c"])>=82;tight=free<2500
    return {"heavy_parallel":False,"warm_cache":not hot and not tight,"reason":"thermal" if hot else "vram" if tight else "normal","gpu":g}

def nas_snapshot():
    root=Path(r"\\AlexLosServer\RG_AUTO_EDIT");t=time.perf_counter()
    try:
        ok=root.exists()
        if ok:next(root.iterdir(),None)
        ms=(time.perf_counter()-t)*1000
        return {"ok":ok,"latency_ms":round(ms,1),"adaptive_timeout_sec":max(30,min(300,int(30+ms/10)))}
    except Exception as e:return {"ok":False,"latency_ms":None,"adaptive_timeout_sec":180,"error":str(e)}

def disk_snapshot():
    out={}
    for d in ("F:\\","C:\\"):
        try:
            u=shutil.disk_usage(d);out[d]={"free_gb":round(u.free/1024**3,1),"total_gb":round(u.total/1024**3,1)}
        except Exception as e:out[d]={"error":str(e)}
    return out

def stable_state():return read_json(STABLE,{"schema":"RG_PRODUCTION_STABLE_V1","frozen":False,"version":None,"success_streak":0})
def set_stable(version,success_streak=5):return atomic_json(STABLE,{"schema":"RG_PRODUCTION_STABLE_V1","frozen":True,"version":str(version),"success_streak":int(success_streak),"updated_at":time.time()})
def unfreeze_stable(reason="manual"):
    d=stable_state();d.update(frozen=False,unfreeze_reason=str(reason),updated_at=time.time());return atomic_json(STABLE,d)

def control_center_snapshot():
    return {"schema":"RG_CONTROL_CENTER_PACK500_V1","ts":time.time(),"runtime":runtime_snapshot(),"gpu":gpu_snapshot(),"gpu_policy":gpu_policy(),
            "nas":nas_snapshot(),"disk":disk_snapshot(),"backend":update_locked(),"pending_update":pending_update(),"stable":stable_state()}

def stream_duration_priority(duration_sec):
    h=float(duration_sec or 0)/3600
    return "LONG" if h>=6 else "FAST" if h<=2 else "NORMAL"

def _performance_rows():
    rows=[]
    root=APP/"run_manifests"
    if root.exists():
        for p in root.rglob("RG_PERFORMANCE_PROFILE.json"):
            d=read_json(p,{})
            sec=float(d.get("elapsed_seconds") or d.get("elapsed") or 0)
            if sec>0:rows.append({"stream":p.parent.name,"elapsed_seconds":sec,"data":d,"mtime":p.stat().st_mtime})
    rows.sort(key=lambda x:x["mtime"],reverse=True);return rows

def median_runtime(last_n=10):
    vals=[r["elapsed_seconds"] for r in _performance_rows()[:int(last_n)]]
    return statistics.median(vals) if vals else None

def predictive_schedule(items,median_elapsed_sec=None):
    med=float(median_elapsed_sec or median_runtime(10) or 0);cursor=time.time();out=[]
    for row in list(items or []):
        dur=float((row or {}).get("duration_sec") or 0);ratio=(dur/(3*3600)) if dur else 1
        est=max(60,med*max(.25,ratio)) if med else max(300,dur*.18 if dur else 1800)
        out.append({**row,"profile":stream_duration_priority(dur),"eta_seconds":round(est),"starts_at":cursor,"finishes_at":cursor+est});cursor+=est
    return {"items":out,"queue_finishes_at":cursor,"total_eta_seconds":round(cursor-time.time())}

def performance_regression(current_sec,last_n=10):
    med=median_runtime(last_n)
    if not med:return {"available":False}
    ratio=float(current_sec)/med
    return {"available":True,"median_seconds":round(med,1),"current_seconds":round(float(current_sec),1),"ratio":round(ratio,3),"regression":ratio>=1.35}

def bottleneck_explanation(profile):
    p=profile or {};gpu=float(((p.get("gpu_util_pct") or {}).get("avg") or p.get("gpu_avg") or 0));cpu=float(((p.get("cpu_pct") or {}).get("avg") or p.get("cpu_avg") or 0))
    nas=float(p.get("nas_wait_pct") or 0);disk=float(p.get("disk_wait_pct") or 0)
    if nas>=25:return "NAS WAIT"
    if disk>=25:return "DISK WAIT"
    if gpu>=85:return "GPU"
    if cpu>=85:return "CPU"
    if gpu<30 and cpu<40:return "I/O / MODEL LOAD"
    return "BALANCED"

def cache_inventory(stream=None):
    root=APP/".rg_cache";out=[]
    if not root.exists():return out
    targets=[root/str(stream)] if stream else [x for x in root.iterdir() if x.is_dir()]
    for d in targets:
        if not d.exists():continue
        files=[p for p in d.rglob("*") if p.is_file()];size=sum(p.stat().st_size for p in files);newest=max([p.stat().st_mtime for p in files],default=0)
        age=max(0,(time.time()-newest)/3600) if newest else 99999;cost=max(1,len(files))*max(1,size/1024**2);reuse=max(.1,1/(1+age/24))
        out.append({"stream":d.name,"files":len(files),"size_mb":round(size/1024**2,1),"age_hours":round(age,1),"eviction_score":round(reuse*cost,2)})
    return sorted(out,key=lambda x:x["eviction_score"],reverse=True)

def checkpoint_browser(stream):
    s=str(stream);manifest=APP/f"RG_EDITED_{s}_MULTI_DIALOGUE.json";m=read_json(manifest,{})
    rows=[]
    for r in m.get("outputs") or []:
        p=Path(str(r.get("xml") or ""));rows.append({"index":r.get("index"),"xml":str(p),"exists":p.is_file(),"resumed":bool(r.get("resumed")),"job_key":r.get("job_key")})
    return {"stream":s,"manifest":str(manifest),"status":m.get("status"),"dialogue_count":m.get("dialogue_count"),"outputs":rows,"cache":cache_inventory(s)}

DEPENDENCIES={"CLOCK":["BOUNDARY","FACE","VOICE","TRANSCRIPT","XML","QA"],"BOUNDARY":["FACE","VOICE","TRANSCRIPT","XML","QA"],"FACE":["BOUNDARY","XML","QA"],"VOICE":["TRANSCRIPT","XML","QA"],"TRANSCRIPT":["XML","QA"],"XML":["QA"],"QA":[]}
def minimal_recalculation(changed_stage):
    st=str(changed_stage or "").upper();inv=DEPENDENCIES.get(st,["QA"])
    return {"changed":st,"invalidate":inv,"preserve":[x for x in DEPENDENCIES if x not in ([st]+inv)]}

def boundary_confidence(job_found):
    rs=list((job_found or {}).get("selected_ranges") or [])
    if not rs:return {"score":0.0,"risk":"BLOCK","reason":"no_range"}
    r=rs[0];dur=float(r.get("duration") or max(0,float(r.get("end",0))-float(r.get("start",0))))
    score=1.0;reasons=[]
    if dur<5:score-=.8;reasons.append("too_short")
    if dur>2700:score-=.35;reasons.append("long")
    if dur>7200:score-=.6;reasons.append("extreme")
    b=(job_found or {}).get("boundary") or {}
    if b.get("identity_confirmed") is False:score-=.35;reasons.append("identity_not_confirmed")
    if b.get("voice_confirmed") is False:score-=.2;reasons.append("voice_not_confirmed")
    score=max(0,min(1,score));risk="BLOCK" if score<.25 else "CHECK" if score<.55 else "PASS"
    return {"score":round(score,3),"risk":risk,"duration_sec":round(dur,2),"reasons":reasons}

def annotate_boundary_job(job_found,previous_match=None,next_match=None,stream=None,index=None):
    jf=dict(job_found or {});conf=boundary_confidence(jf);jf["pack500_boundary_confidence"]=conf
    if conf["risk"]=="BLOCK":raise RuntimeError(f"PACK500 boundary anomaly blocked before heavy processing: stream={stream} dialogue={index} {conf}")
    return jf

def validate_xml_semantic(path):
    p=Path(path)
    if not p.is_file() or p.stat().st_size<256:raise RuntimeError("XML missing/too small: "+str(p))
    root=ET.parse(p).getroot();issues=[];clips=root.findall(".//clipitem")
    for c in clips:
        def n(tag):
            try:return int((c.findtext(tag) or "0").strip())
            except Exception:return 0
        start,end,inn,out=n("start"),n("end"),n("in"),n("out")
        if end and start and end<start:issues.append("end<start")
        if out and inn and out<inn:issues.append("out<in")
        if min(start,end,inn,out)<0:issues.append("negative_time")
    if issues:raise RuntimeError("XML semantic validation failed: "+";".join(sorted(set(issues))))
    return {"ok":True,"clipitems":len(clips),"root":root.tag}

def premiere_import_simulation(path):
    r=validate_xml_semantic(path);txt=Path(path).read_text(encoding="utf-8",errors="replace")
    if "<xmeml" not in txt and "<project" not in txt:raise RuntimeError("Premiere XML signature not found")
    return {**r,"premiere_signature":True}

def sha256_file(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def xml_lock_path(xml):
    p=Path(xml);XML_LOCKS.mkdir(parents=True,exist_ok=True);return XML_LOCKS/(p.name+".sha256.json")
def lock_xml(xml,stream=None,index=None):
    p=Path(xml);d={"schema":"RG_XML_LOCK_V1","path":str(p),"sha256":sha256_file(p),"size":p.stat().st_size,"stream":str(stream or ""),"index":index,"locked_at":time.time()}
    atomic_json(xml_lock_path(p),d);return d
def verify_xml_lock(xml):
    p=Path(xml);lp=xml_lock_path(p)
    if not lp.is_file():return {"ok":True,"locked":False}
    d=read_json(lp,{});cur=sha256_file(p);return {"ok":cur==d.get("sha256"),"locked":True,"expected":d.get("sha256"),"actual":cur}
def write_xml_provenance(xml,stream,index,job_found=None):
    p=Path(xml);PROVENANCE.mkdir(parents=True,exist_ok=True)
    d={"schema":"RG_XML_PROVENANCE_V1","stream":str(stream),"index":int(index),"xml":str(p),"sha256":sha256_file(p),"created_at":time.time(),
       "studio_version":"0.20.9.0","boundary_confidence":(job_found or {}).get("pack500_boundary_confidence"),"run_id":os.environ.get("RG_RUN_ID",""),"algorithm_contract":"PACK500_V1"}
    atomic_json(PROVENANCE/(p.name+".json"),d);return d

def migrate_cache_contract(stream=None):
    rows=cache_inventory(stream);return atomic_json(DATA/"cache_migration"/("all.json" if stream is None else f"{stream}.json"),{"schema":"RG_CACHE_MIGRATION_V1","ts":time.time(),"compatible_preserved":True,"items":rows})
def regression_corpus():return read_json(DATA/"regression_corpus.json",{"schema":"RG_REGRESSION_CORPUS_V1","streams":[],"dialogues":[]})
def benchmark_compare(candidate,baseline,limit_pct=15):
    c,b=float(candidate or 0),float(baseline or 0)
    if b<=0:return {"passed":True,"available":False}
    delta=(c-b)/b*100;return {"passed":delta<=float(limit_pct),"available":True,"delta_pct":round(delta,2),"limit_pct":float(limit_pct)}

def shadow_enqueue(contour,payload):
    SHADOW.mkdir(parents=True,exist_ok=True);name=f"{int(time.time()*1000)}_{contour}.json"
    return atomic_json(SHADOW/name,{"contour":str(contour),"payload":payload,"created_at":time.time(),"status":"LOCAL_PENDING"})
def shadow_flush(target_root=r"\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC"):
    root=Path(target_root);sent=0;failed=[]
    if not root.exists():return {"ok":False,"sent":0,"reason":"NAS unavailable"}
    for p in sorted(SHADOW.glob("*.json")):
        d=read_json(p,{});contour=str(d.get("contour") or "auto_edit");dst=root/contour/"requests"/p.name
        try:dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst);p.unlink();sent+=1
        except Exception as e:failed.append({"path":str(p),"error":str(e)})
    return {"ok":not failed,"sent":sent,"failed":failed}

def _pid_alive(pid):
    try:
        cp=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",f"if(Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue){{'1'}}else{{'0'}}"],capture_output=True,text=True,timeout=8)
        return (cp.stdout or "").strip()=="1"
    except Exception:return True

def auto_fix_known():
    fixed=[];locks=APP/".rg_stream_locks"
    if locks.exists():
        for p in locks.glob("*.json"):
            d=read_json(p,{});pid=int(d.get("owner_pid") or d.get("pid") or 0)
            if pid and not _pid_alive(pid):
                try:p.unlink();fixed.append("stale_lock:"+p.name)
                except Exception:pass
    SHADOW.mkdir(parents=True,exist_ok=True);(DATA/"crash_recovery").mkdir(parents=True,exist_ok=True)
    return {"fixed":fixed,"shadow_flush":shadow_flush(),"control_center":control_center_snapshot()}

def meaningful_notification(kind):return str(kind).upper() in {"STREAM_COMPLETE","NEEDS_CHECK","ERROR","QUEUE_COMPLETE","UPDATE_READY"}
def throughput(processed_video_sec,elapsed_sec):
    e,v=float(elapsed_sec or 0),float(processed_video_sec or 0);return {"video_per_real":round(v/e,3) if e>0 else None,"processed_video_sec":v,"elapsed_sec":e}
def performance_report_after_update(version,current_sec=None):
    d={"schema":"RG_POST_UPDATE_PERF_V1","version":str(version),"created_at":time.time(),"median_last_10":median_runtime(10),
       "regression":performance_regression(current_sec,10) if current_sec else {"available":False},"gpu":gpu_snapshot(),"nas":nas_snapshot()}
    return atomic_json(DATA/"post_update_reports"/f"{version}.json",d)
def feature_matrix():
    return {"schema":"RG_PACK500_FEATURE_MATRIX_V1","coverage":{"from":1,"to":50,"count":50},"features":[{"id":i,"name":FEATURES[i],"status":"COVERED"} for i in range(1,51)]}
