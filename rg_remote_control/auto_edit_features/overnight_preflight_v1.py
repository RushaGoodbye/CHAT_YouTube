#!/usr/bin/env python3
# Read-only RG Auto Edit night batch readiness check.
from __future__ import annotations
import ast, json, os, re, shutil, subprocess, sys, time
import xml.etree.ElementTree as ET
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
DATA=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
LOCAL=Path(os.environ.get("LOCALAPPDATA",""))/"RG_Auto_Edit"
QUEUE=LOCAL/"studio_batch_queue.json"
TARGETS=[str(s) for s in (json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("args") or {}).get("streams",[])] if len(sys.argv)>1 else []
def read_json(p):
    try:return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as e:return {"error":type(e).__name__,"exists":p.is_file()}
def qa_report_is_valid(postrun):
    """Fail closed when postrun results are absent, malformed or contradictory."""
    if not isinstance(postrun,dict) or postrun.get("passed") is not True:
        return False
    checks=postrun.get("checks")
    return isinstance(checks,list) and bool(checks) and all(
        isinstance(check,dict) and check.get("ok") is True for check in checks
    )
def stat_file(p):
    try:
        st=p.stat();return {"exists":True,"bytes":st.st_size,"modified":round(st.st_mtime)}
    except FileNotFoundError:return {"exists":False}
    except Exception as e:return {"error":repr(e)}
def cmd(args,timeout=15):
    try:
        p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding="utf-8",errors="replace",timeout=timeout,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        return {"exit":p.returncode,"stdout":p.stdout[-10000:],"stderr":p.stderr[-1000:]}
    except Exception as e:return {"error":str(e)[:300]}
out={"schema":"RG_OVERNIGHT_PREFLIGHT_V1","timestamp":time.time(),"read_only":True,"targets":TARGETS}
out["version"]=(APP/"rg_studio_version.py").read_text(encoding="utf-8-sig",errors="replace").splitlines()[:4] if (APP/"rg_studio_version.py").is_file() else None
out["queue"]=read_json(QUEUE)
out["modules"]={}
for n in ("rg_studio_ui.py","rg_studio_main.py","rg_studio_postrun.py","rg_multi_dialogue.py","rg_auto_edit_one_button.py","rg_server_resolver.py","rg_final_compilation.py"):
    p=APP/n
    try:
        source=p.read_text(encoding="utf-8-sig")
        ast.parse(source,filename=n)
        out["modules"][n]={"syntax":"PASS","bytes":p.stat().st_size}
    except Exception as e:out["modules"][n]={"syntax":"FAIL","error":str(e)[:200]}
out["runtime"]=stat_file(Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe"))
out["disks"]={}
for drive in ("F:\\","D:\\","C:\\"):
    try:
        d=shutil.disk_usage(drive)
        out["disks"][drive]={"free_gb":round(d.free/2**30,1),"total_gb":round(d.total/2**30,1)}
    except Exception as e:out["disks"][drive]={"error":str(e)[:100]}
out["processes"]=cmd(["powershell","-NoProfile","-NonInteractive","-Command",r"$p=Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -and ($_.CommandLine -match 'rg_studio_main|rg_auto_edit_one_button|rg_multi_dialogue|rg_production_wrapper|rg_studio_update|rg_auto_edit.*python')}; $p | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress -Depth 3"],timeout=20)
out["gpu"]=cmd(["nvidia-smi","--query-gpu=name,memory.free,memory.total,utilization.gpu,temperature.gpu","--format=csv,noheader,nounits"],timeout=10)
out["sleep"]=cmd(["powercfg","/query","SCHEME_CURRENT","SUB_SLEEP","STANDBYIDLE"],timeout=10)
out["update_state"]=read_json(DATA/"update_supervisor_state.json")
out["inputs"]={}
candidate_roots={}
for base in (APP,DATA,LOCAL):
    for name in ("rg_auto_edit_config.json","studio_settings.json","rg_studio_settings.json","settings.json","ui_state.json","studio_config.json"):
        p=base/name
        if not p.is_file():continue
        data=read_json(p)
        if isinstance(data,dict):
            for k,v in data.items():
                if re.search(r"(video|audio|screen|folder|root|source|output).*",str(k),re.I) and isinstance(v,str) and len(v)<320:
                    candidate_roots[k]=v
out["configured_paths"]=candidate_roots
# Only resolve user-supplied numbers or existing queued stream; no scans of whole NAS.
queue=out["queue"] if isinstance(out["queue"],dict) else {}
streams=list(dict.fromkeys(TARGETS or queue.get("queue",[])))
for st in streams[:25]:
    if not re.fullmatch(r"\d{3,5}",str(st)):continue
    row={"stream":st,"result_dir":stat_file(APP/str(st)),"run_log":stat_file(APP/"run_manifests"/str(st)/"STUDIO_RUN.log")}
    for kind,ext in (("video",".mp4"),("audio",".mp3")):
        roots=[v for k,v in candidate_roots.items() if kind in k.lower() and isinstance(v,str)]
        row[kind+"_candidates"]=[{"file":str(Path(root)/(str(st)+ext)),"exists":(Path(root)/(str(st)+ext)).is_file()} for root in roots[:5]]
    out["inputs"][st]=row

# RG_OVERNIGHT_INPUT_RESOLVER_V2: the exact same network root and resolver as Studio.
try:
    cfg=read_json(APP/"rg_server_paths.json")
    assert isinstance(cfg,dict) and cfg.get("video_root") and cfg.get("audio_root") and cfg.get("screen_root"),"Studio path config missing"
    out["actual_roots"]={k:str(cfg[k]) for k in ("video_root","audio_root","screen_root")}
    sys.path.insert(0,str(APP))
    from rg_server_resolver import resolve_video,resolve_audio,resolve_screenshots
    targets=TARGETS or list((out["queue"] or {}).get("queue") or [])
    for st in targets[:25]:
        st=str(st)
        row=out["inputs"].setdefault(st,{"stream":st})
        for kind,func,rootkey in (
            ("video",resolve_video,"video_root"),
            ("audio",resolve_audio,"audio_root"),
            ("screenshots",resolve_screenshots,"screen_root")):
            try:
                result=func(cfg[rootkey],st)
                if kind=="screenshots":
                    paths=list(result)
                    row[kind]={"ok":bool(paths),"count":len(paths),"sample":[{"name":p.name,"bytes":p.stat().st_size} for p in paths[:5]],"all_nonempty":all(p.stat().st_size>0 for p in paths)}
                else:
                    selected,root,candidates=result
                    row[kind]={"ok":selected.is_file() and selected.stat().st_size>0,
                               "name":selected.name,"bytes":selected.stat().st_size,
                               "candidates":len(candidates)}
            except Exception as exc:
                row[kind]={"ok":False,"error":type(exc).__name__+": "+str(exc)[:210]}
        rs=read_json(DATA/"run_state"/st/"RUN_STATE.json")
        row["last_run_status"]=rs.get("status") if isinstance(rs,dict) else None
        row["last_run_error"]=str(rs.get("error_tail") or "")[-350:] if isinstance(rs,dict) else None
        row["prior_backend_error"]=str(row["last_run_status"] or "").upper() in {"BACKEND_ERROR","ERROR","FAILED","CRASHED"}
        postrun=read_json(APP/st/"RG_POSTRUN_QA.json")
        row["postrun_passed"]=postrun.get("passed") if isinstance(postrun,dict) else None
        checks=postrun.get("checks") if isinstance(postrun,dict) else None
        row["qa_checks_failed"]=bool(
            isinstance(checks,list) and any(not isinstance(c,dict) or c.get("ok") is not True for c in checks)
        )
        row["qa_report_valid"]=qa_report_is_valid(postrun)
        mani=read_json(APP/("RG_EDITED_"+st+"_MULTI_DIALOGUE.json"))
        if not isinstance(mani,dict):mani={}
        outputs=mani.get("outputs") or []
        row["manifest_dialogue_count"]=mani.get("dialogue_count")
        row["manifest_output_count"]=len(outputs) if isinstance(outputs,list) else 0
        try:
            expected=int(row["manifest_dialogue_count"])
            if expected<=0 or expected>1000:
                raise ValueError("Invalid dialogue count")
        except (TypeError,ValueError,OverflowError):
            expected=0
            row["manifest_error"]="INVALID_DIALOGUE_COUNT"
        paths=[Path(x["xml"]) for x in outputs if isinstance(x,dict)
               and isinstance(x.get("xml"),str) and x["xml"].strip()] if isinstance(outputs,list) else []
        row["xml_existing"]=sum(p.is_file() and p.stat().st_size>0 for p in paths)
        row["xml_valid"]=0
        row["xml_invalid"]=[]
        for p in paths:
            try:
                if not p.is_file() or p.stat().st_size==0:
                    raise ValueError("missing or empty")
                root_xml=ET.parse(p).getroot()
                sequence=root_xml.find(".//sequence")
                if sequence is None:
                    raise ValueError("missing Premiere sequence")
                if not sequence.findall("./media/video/track/clipitem"):
                    raise ValueError("missing video clips")
                if not sequence.findall("./media/audio/track/clipitem"):
                    raise ValueError("missing audio clips")
                row["xml_valid"]+=1
            except (OSError, ET.ParseError, ValueError) as exc:
                row["xml_invalid"].append({"name":p.name,"reason":str(exc)[:100]})
        row["xml_unique"]=len({str(p).casefold() for p in paths})==len(paths)
        row["complete_state"]=str(row["last_run_status"] or "").upper()=="COMPLETE"
        row["complete_manifest"]=bool(expected>0 and isinstance(outputs,list)
                                      and len(outputs)==expected and len(paths)==expected
                                      and row["xml_existing"]==expected
                                      and row["xml_valid"]==expected and row["xml_unique"])
        # Do not skip a stream merely because XML files or COMPLETE state exist.
        # Failed or absent postrun QA requires inspection, not silent skip.
        row["already_complete"]=bool(row["complete_manifest"] and row["qa_report_valid"] and
                                     not row["prior_backend_error"] and
                                     not (row.get("audio",{}).get("candidates",0)>1))
        row["requires_qa_review"]=bool((row["complete_state"] or row["complete_manifest"]) and not row["already_complete"])
        row["inputs_ready"]=all(row.get(k,{}).get("ok") for k in ("video","audio","screenshots"))

        if isinstance(postrun,dict) and "checks" in postrun:
            row["qa_failures"]=[{"name":str(c.get("name","")),"detail":str(c.get("message") or c.get("reason") or c.get("detail") or "")[:230]}
                                for c in (postrun.get("checks") or []) if isinstance(c,dict) and c.get("ok") is not True][:12]
        if st in ("886","901"):
            runlog=APP/"run_manifests"/st/"STUDIO_RUN.log"
            if runlog.is_file():
                lines=runlog.read_text(encoding="utf-8",errors="replace").splitlines()
                row["run_log_errors"]=[x[-350:] for x in lines if any(key in x.lower() for key in ("runtimeerror:","traceback","error:","failed","blocked","cuda error"))][-12:]
        if st=="903":
            from rg_server_resolver import AUDIO_EXTS, _contains_stream_number
            root=Path(cfg["audio_root"])
            choices=[p for p in root.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS and _contains_stream_number(p.name,st)]
            choices=sorted(choices,key=lambda x:x.name.lower())
            ffprobe=shutil.which("ffprobe") or str(APP/"tools"/"ffprobe.exe")
            if not Path(ffprobe).is_file() and not shutil.which("ffprobe"):
                ffprobe=None
            row["audio_candidates_detailed"]=[]
            for p in choices:
                item={"name":p.name,"size_mb":round(p.stat().st_size/1048576)}
                if ffprobe:
                    probe=cmd([str(ffprobe),"-v","error","-show_entries","format=duration:stream=codec_type,sample_rate,channels","-of","json",str(p)],timeout=20)
                    try:
                        parsed=json.loads(probe.get("stdout") or "{}")
                        item["duration_sec"]=round(float(parsed.get("format",{}).get("duration") or 0),1)
                        item["audio_streams"]=len([s for s in parsed.get("streams",[]) if s.get("codec_type")=="audio"])
                    except Exception:item["probe_error"]=probe.get("stderr") or probe.get("error")
                row["audio_candidates_detailed"].append(item)
            if ffprobe:
                video=Path(cfg["video_root"])/str(st+".mp4")
                probe=cmd([str(ffprobe),"-v","error","-show_entries","format=duration","-of","json",str(video)],timeout=20)
                try:row["video_duration_sec"]=round(float(json.loads(probe.get("stdout") or "{}").get("format",{}).get("duration")),1)
                except Exception:row["video_probe_error"]=probe.get("stderr") or probe.get("error")

        row["audio_ambiguous"]=bool(row.get("audio",{}).get("candidates",0)>1)
        # Errors and ambiguous source audio require review even if stale
        # manifests and QA reports still claim the stream is complete.
        row["night_action"]=("REVIEW_BACKEND" if row["prior_backend_error"] else
                             "REVIEW_AUDIO" if row["audio_ambiguous"] else
                             "REVIEW_QA" if row["requires_qa_review"] else
                             "SKIP_COMPLETE" if row["already_complete"] else
                             "MISSING_INPUT" if not row["inputs_ready"] else
                             "RUN_EXPECTED")
except Exception as exc:
    out["resolver_error"]=repr(exc)

out["checks"]={
"queue_not_empty":bool(queue.get("queue")),
"queue_running":bool(queue.get("running")),
"stale_failed_rows":[r.get("stream") for r in queue.get("rows",[]) if r.get("status")=="ПОМИЛКА"],
"module_syntax_ok":all(x.get("syntax")=="PASS" for x in out["modules"].values()),
"runtime_exists":out["runtime"].get("exists") is True,
"data_free_gb":out["disks"].get("F:\\",{}).get("free_gb"),
}
print("RG_OVERNIGHT_PREFLIGHT|"+json.dumps(out,ensure_ascii=False,default=str),flush=True)
