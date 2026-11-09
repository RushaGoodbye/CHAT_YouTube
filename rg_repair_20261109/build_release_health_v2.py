"""Assemble Release Health V2 without modifying active Studio."""
from pathlib import Path
import hashlib,json,sys,shutil,ast
from stage_release_health_v2 import patch_source

TAG="RG_REPAIR_20261109_V2_RELEASE"
APP=Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def build(dest):
    source=APP/"rg_release_health_gate.py"
    dest=Path(dest)
    candidate=dest/"candidate"
    candidate.mkdir(parents=True,exist_ok=True)
    out=candidate/source.name
    out.write_text(patch_source(source.read_text(encoding="utf-8")),encoding="utf-8")
    ast.parse(out.read_text(encoding="utf-8"))
    manifest={"version":TAG,"stage":"NOT_INSTALLED","files":{
        source.name:{"source_sha256":sha(source),"candidate_sha256":sha(out)}
    },"release_only":True,"automated_export_authorized":False,
       "manual_review_904_3_required":True}
    (candidate/"RG_REPAIR_REPORT.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    folder=Path(__file__).parent
    for x in ["install_v2.py","INSTALL_RELEASE_HEALTH_V2.cmd","ROLLBACK_RELEASE_HEALTH_V2.cmd","README_RELEASE_HEALTH_V2.txt"]:
        shutil.copy2(folder/x,dest/x)
    print("RGREPAIRV2|BUILT_STAGED_ONLY|"+str(dest))
    print("RGREPAIRV2|SOURCE_SHA256|"+manifest["files"][source.name]["source_sha256"])
    print("RGREPAIRV2|PATCH_SHA256|"+manifest["files"][source.name]["candidate_sha256"])
if __name__=="__main__":build(sys.argv[1])
