"""Copy evidence into a new immutable NAS directory, outside agent commands."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import zipfile
from rg_smoking_compliance import sha256_file,ReviewRequired
from run_real_four_layer_qa import APP,HOLD,protected,ROOT

NAS=Path(r'\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\smoking_release\20261009')


def run(output,artifact):
    output=Path(output); artifact=Path(artifact)
    before=protected()
    commit=os.environ['GITHUB_SHA']
    target=NAS/commit
    if target.exists(): raise ReviewRequired('REFUSE_OVERWRITING_NAS_CHECKPOINT')
    artifact.mkdir(parents=True,exist_ok=True)
    archive=output/'RG_SMOKING_RELEASE_EVIDENCE.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(output.rglob('*')):
            if not p.is_file() or p==archive or 'yolo_config' in p.parts: continue
            z.write(p,str(p.relative_to(output)))
        for p in sorted(Path(__file__).parent.glob('*.py')): z.write(p,'replay/'+p.name)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None: raise ReviewRequired('EVIDENCE_ARCHIVE_CORRUPT')
    baseline=output/'STUDIO_0_20_20_3_SOURCE_BASELINE.zip'
    with zipfile.ZipFile(baseline,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(APP.glob('*.py')):
            if any(t in p.name.lower() for t in ('token','credential','secret','oauth')): continue
            z.write(p,p.name)
    manifest=dict(schema='RG_SMOKING_NAS_CHECKPOINT_V1',commit=commit,
        run_id=os.environ.get('GITHUB_RUN_ID'),production_installed=False,release_allowed=False,
        protected_studio_hashes=before,quarantine_886_5_sha256=sha256_file(HOLD),
        archive_sha256=sha256_file(archive),source_baseline_sha256=sha256_file(baseline),
        nas_directory=str(target),previous_real_candidate={})
    previous=ROOT/'smoking_release_candidate_v1/1a9e4537034d7fe0460ffced3f47bb351df1e186/RG_SMOKING_REAL_FOUR_LAYER_CANDIDATE_QA_V1.zip'
    if previous.is_file(): manifest['previous_real_candidate']={previous.name:sha256_file(previous)}
    try:
        target.mkdir(parents=True,exist_ok=False)
        for p in [archive,baseline]+([previous] if previous.is_file() else []):
            dst=target/p.name; shutil.copyfile(p,dst)
            if sha256_file(dst)!=sha256_file(p): raise ReviewRequired('NAS_COPY_HASH_MISMATCH')
        manifest['nas_checkpoint_verified']=True
    except Exception as exc:
        manifest['nas_checkpoint_verified']=False; manifest['error']=str(exc)
        raise
    finally:
        manifest['studio_changed']=before!=protected()
        (output/'checkpoint.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        shutil.copyfile(output/'checkpoint.json',artifact/'checkpoint.json')
        shutil.copyfile(archive,artifact/archive.name)
        if target.is_dir(): shutil.copyfile(output/'checkpoint.json',target/'checkpoint.json')
        if manifest['studio_changed']: raise ReviewRequired('PROTECTED_STUDIO_CHANGED')
    print('RG_NAS_CHECKPOINT|'+json.dumps({k:manifest[k] for k in ('nas_directory','nas_checkpoint_verified','production_installed','release_allowed','studio_changed')}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--output',required=True); p.add_argument('--artifact',required=True)
    a=p.parse_args(); run(a.output,a.artifact)
