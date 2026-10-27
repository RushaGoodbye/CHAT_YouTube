#!/usr/bin/env python3
"""Determine whether installed Studio can safely launch 907 using embedded MP4 audio.
Fail closed: no media writes, no source patch, no queue mutation, no job launch."""
import ast,json,re
from pathlib import Path
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
NAMES=["rg_multi_dialogue.py","rg_auto_edit_one_button.py","rg_server_resolver.py","rg_studio_main.py"]
def main():
 result={"schema":"RG907_DIRECT_MP4_AUDIO_LAUNCH_PREFLIGHT_V1","stream":"907","read_only":True,
         "job_started":False,"files_changed":0,"video_exists":Path(r"\\Desktop-v7gg0en\record\907.mp4").is_file(),
         "screenshots":[Path(r"\\Desktop-v7gg0en\record\Screens")/f"907-{i}.jpg" for i in range(1,9)]}
 result["screenshots_ok"]=all(p.is_file() for p in result.pop("screenshots"))
 modules={}
 for n in NAMES:
  p=APP/n
  if not p.is_file():modules[n]={"exists":False};continue
  s=p.read_text(encoding="utf-8-sig")
  try:tree=ast.parse(s)
  except SyntaxError as e:modules[n]={"exists":True,"syntax":"FAIL","reason":str(e)};continue
  functions=[a.name for a in tree.body if isinstance(a,(ast.FunctionDef,ast.AsyncFunctionDef))]
  audio_lines=[{"line":i,"code":l.strip()[:180]} for i,l in enumerate(s.splitlines(),1)
         if re.search(r"audio_root|resolve_audio|audio_stream|video_audio|embedded_audio|audio_source",l,re.I)]
  modules[n]={"exists":True,"syntax":"PASS","functions":functions[:65],
              "audio_code_excerpt":audio_lines[:40]}
 result["modules"]=modules
 result["safe_to_launch_automatically"]=False
 result["reason"]="Need prove installed audio-input contract and anchor injection before write operations"
 print("RG907|DIRECT_MP4_LAUNCH_PLAN|"+json.dumps(result,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
