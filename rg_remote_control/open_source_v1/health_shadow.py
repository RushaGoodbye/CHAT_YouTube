#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only RG Auto Edit Windows resource snapshot via optional psutil (BSD-3)."""
from __future__ import annotations
import json
import os
from pathlib import Path
import platform
import sys
import time

ALLOWED={"python.exe","pythonw.exe","rg auto edit studio.exe",
         "rg auto edit.exe","premiere pro.exe","afterfx.exe",
         "ffmpeg.exe","steam.exe","obs64.exe"}
SCHEMA="RG_OSS_HEALTH_SHADOW_V1"

def read_only_snapshot(*,psutil_module=None):
    if psutil_module is None:
        import psutil as psutil_module
    ps=psutil_module
    processes=[]
    for proc in ps.process_iter(attrs=["pid","name"]):
        try:
            name=str(proc.info.get("name") or "")
            if name.lower() not in ALLOWED:
                continue
            mem=proc.memory_info()
            io=proc.io_counters() if hasattr(proc,"io_counters") else None
            processes.append({
                "pid":proc.pid,"name":name,
                "memory_mb":round(mem.rss/1024**2,1),
                "io_read_bytes":getattr(io,"read_bytes",None),
                "io_write_bytes":getattr(io,"write_bytes",None),
            })
        except (ps.NoSuchProcess,ps.AccessDenied,ps.ZombieProcess,OSError):
            continue
    drives={}
    for drive in (r"F:\",r"D:\"):
        try:
            if not os.path.isdir(drive):
                drives[drive]={"available":False}
                continue
            usage=ps.disk_usage(drive)
            drives[drive]={"available":True,
                           "percent_used":usage.percent,
                           "free_gb":round(usage.free/1024**3,1)}
        except (OSError,PermissionError):
            drives[drive]={"available":False}
    return {
        "schema":SCHEMA,"read_only":True,
        "production_modified":False,
        "current_cpu_percent":ps.cpu_percent(interval=0.1),
        "memory_percent_used":ps.virtual_memory().percent,
        "drives":drives,"processes":processes,
        "note":"Disk percent is capacity used, NOT real-time drive utilization. No process is killed."
    }

def main():
    try:
        report=read_only_snapshot()
    except ModuleNotFoundError:
        report={"schema":SCHEMA,"status":"NOT_INSTALLED",
          "read_only":True,"production_modified":False,
          "component":"psutil"}
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
