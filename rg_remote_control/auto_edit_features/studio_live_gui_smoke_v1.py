#!/usr/bin/env python3
"""Read-only Win32 responsiveness probe for installed RG Auto Edit Studio.

Does not launch, close, manipulate or focus application windows.
When no Studio GUI is visible to the runner session, result is UNTESTED,
not a pass. No stream/media/queue/XML operations.
"""
from __future__ import annotations
import ast
import ctypes
from ctypes import wintypes
import json
import re
from pathlib import Path

APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
REQUIRED=("rg_studio_ui.py","rg_multi_dialogue.py",
          "rg_auto_edit_one_button.py","rg_studio_postrun.py")
WINDOW_TERMS=("RG AUTO EDIT","AUTO EDIT STUDIO")
WM_NULL=0
SMTO_ABORTIFHUNG=0x0002
SMTO_BLOCK=0x0001

def source_check(root):
    result={}
    for name in REQUIRED:
        path=root/name
        if not path.is_file():
            result[name]="MISSING"
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8-sig"),filename=name)
            result[name]="PASS"
        except (SyntaxError,UnicodeError):
            result[name]="FAIL"
    version_path=root/"rg_studio_version.py"
    version=None
    if version_path.is_file():
        match=re.search(r"STUDIO_VERSION\s*=\s*['\"]([^'\"]+)", version_path.read_text(encoding="utf-8-sig"))
        if match:version=match.group(1)
    return result,version

def title_matches(value):
    s=value.strip().upper()
    return bool(s) and any(term in s for term in WINDOW_TERMS)

def visible_windows():
    u=ctypes.windll.user32
    u.EnumWindows.argtypes=[ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM),
                            wintypes.LPARAM]
    u.EnumWindows.restype=wintypes.BOOL
    u.GetWindowTextLengthW.argtypes=[wintypes.HWND]
    u.GetWindowTextLengthW.restype=ctypes.c_int
    u.GetWindowTextW.argtypes=[wintypes.HWND,ctypes.c_wchar_p,ctypes.c_int]
    u.IsWindowVisible.argtypes=[wintypes.HWND]
    u.IsWindowVisible.restype=wintypes.BOOL
    u.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowThreadProcessId.restype=wintypes.DWORD
    u.SendMessageTimeoutW.restype=wintypes.LPARAM
    u.SendMessageTimeoutW.argtypes=[
        wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM,
        wintypes.UINT,wintypes.UINT,ctypes.POINTER(ctypes.c_size_t)]
    out=[]
    CALLBACK=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    @CALLBACK
    def enum(hwnd,ctx):
        if not u.IsWindowVisible(hwnd):return True
        n=u.GetWindowTextLengthW(hwnd)
        if not (0<n<512):return True
        buf=ctypes.create_unicode_buffer(n+1)
        u.GetWindowTextW(hwnd,buf,n+1)
        if not title_matches(buf.value):return True
        pid=wintypes.DWORD(0)
        u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        response=ctypes.c_size_t(0)
        ok=bool(u.SendMessageTimeoutW(hwnd,WM_NULL,0,0,
            SMTO_ABORTIFHUNG|SMTO_BLOCK,750,ctypes.byref(response)))
        out.append({"pid":int(pid.value),"responsive":ok,
                    "title":buf.value[:100]})
        return True
    if not u.EnumWindows(enum,0):raise RuntimeError("EnumWindows failed")
    return out

def report(app=APP):
    sources,version=source_check(app)
    found=visible_windows()
    gui=("NOT_TESTED_NO_VISIBLE_WINDOW" if not found else
         "RESPONSIVE" if any(x["responsive"] for x in found) else "HUNG")
    return {"schema":"RG_STUDIO_LIVE_GUI_SMOKE_V1","read_only":True,
            "studio_version":version,"required_source_syntax":sources,
            "gui_result":gui,"window_count":len(found),
            "windows":found,"tested_real_gui":bool(found),
            "media_writes":0,"xml_writes":0,"queue_writes":0,
            "studio_restarted":False}

if __name__=="__main__":
    print("RG_STUDIO_LIVE_GUI_PROBE|"+json.dumps(report(),ensure_ascii=False),flush=True)
