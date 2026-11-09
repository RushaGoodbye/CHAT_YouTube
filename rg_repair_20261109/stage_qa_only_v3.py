"""RG Repair V3: teach Studio QA-only action to accept historical QA_FAILED
when a current complete manifest proves every existing primary XML.
No montage, no queue mutations, no export bypass in this patch.
"""
from __future__ import annotations
import ast,hashlib,json,shutil
from pathlib import Path
SOURCE=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App\rg_studio_ui.py")
VERSION="RG_REPAIR_20261109_V3_QA_ONLY"
OLD="""            _complete=(str(data.get('status'))=='DIALOGUES_COMPLETE'
                       and expected>0 and len(_manifest_rows)==expected)"""
NEW="""            # RG_QA_ONLY_HISTORIC_QA_FAILED_V3:
            # QA_FAILED means backend has finished but an OLD QA failed.
            # Recheck only when the current manifest and exact XMLs validate.
            # _primary_outputs below still strictly verifies filename/screenshot
            # identities and current-run completeness. No backend is launched.
            _complete=(str(data.get('status')) in ('DIALOGUES_COMPLETE','QA_FAILED')
                       and expected>0 and len(_manifest_rows)==expected)"""
def patch(source):
    if source.count(OLD)!=1:raise RuntimeError(f"UI_QA_ONLY_ANCHOR_COUNT_{source.count(OLD)}")
    out=source.replace(OLD,NEW,1)
    ast.parse(out)
    return out
def build(folder):
    dest=Path(folder);c=dest/"candidate";c.mkdir(parents=True,exist_ok=True)
    out=c/SOURCE.name
    out.write_text(patch(SOURCE.read_text(encoding="utf-8")),encoding="utf-8")
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    manifest={"version":VERSION,"stage":"NOT_INSTALLED",
              "files":{SOURCE.name:{"source_sha256":digest(SOURCE),"candidate_sha256":digest(out)}},
              "scope":"QA-only complete manifest recognition","montage_changes":False,
              "auto_export_enabled":False,"904_missing_index_still_blocked":True}
    (c/"RG_REPAIR_REPORT.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    root=Path(__file__).parent
    for name in ("install_v3.py","INSTALL_QA_ONLY_V3.cmd","ROLLBACK_QA_ONLY_V3.cmd","README_QA_ONLY_V3.txt"):
        shutil.copy2(root/name,dest/name)
    print("RGV3|STAGED|"+str(dest))
    print("RGV3|ORIGINAL_SHA|"+manifest["files"][SOURCE.name]["source_sha256"])
    print("RGV3|UPDATED_SHA|"+manifest["files"][SOURCE.name]["candidate_sha256"])
if __name__=="__main__":
    import sys
    build(sys.argv[1])
