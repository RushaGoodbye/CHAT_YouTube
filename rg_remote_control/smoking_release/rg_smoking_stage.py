"""Build a pinned Studio copy for integration tests, never update the live app."""
from __future__ import annotations
import ast
from pathlib import Path
import shutil
from rg_smoking_compliance import ReviewRequired,sha256_file

GATE_BASELINE_SHA='c0627c95b7152b0fcc163fa547ea84b052fb8a4d5e9086c476ce20ff34e2f784'


def patched_gate(text):
    old="VERSION='RG_FINAL_RELEASE_GATE_V2_PRODUCTION'"
    marker="    if kind=='dialogue':"
    if text.count(old)!=1 or text.count(marker)!=1:
        raise ReviewRequired('STUDIO_GATE_BASELINE_STRUCTURE_CHANGED')
    text=text.replace(old,"from rg_smoking_studio_gate import evaluate_for_xml\nVERSION='RG_FINAL_RELEASE_GATE_V3_SMOKING_RC2'")
    text=text.replace(marker,"    smoking=evaluate_for_xml(x); checks['smoking_compliance']=smoking\n"
        "    if not smoking.get('release_allowed',False): failures.append('SMOKING_COMPLIANCE_REVIEW_REQUIRED')\n"+marker)
    ast.parse(text)
    return text


def stage_app(app,output):
    app=Path(app); output=Path(output)
    if app.resolve()==output.resolve() or app.resolve() in output.resolve().parents:
        raise ReviewRequired('STAGING_INSIDE_LIVE_STUDIO_FORBIDDEN')
    gate=app/'rg_final_release_gate.py'
    if sha256_file(gate)!=GATE_BASELINE_SHA: raise ReviewRequired('INSTALLED_STUDIO_GATE_CHANGED')
    output.mkdir(parents=True,exist_ok=False)
    for p in app.glob('*.py'):
        if any(word in p.name.lower() for word in ('token','credential','secret','oauth')): continue
        shutil.copyfile(p,output/p.name)
    (output/gate.name).write_text(patched_gate(gate.read_text(encoding='utf-8-sig')),encoding='utf-8')
    for p in Path(__file__).parent.glob('rg_smoking_*.py'): shutil.copyfile(p,output/p.name)
    return dict(installed_gate_sha256=GATE_BASELINE_SHA,staged_gate_sha256=sha256_file(output/gate.name),
        staged_directory=str(output),production_installed=False)
