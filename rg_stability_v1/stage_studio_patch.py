"""Build a Stability V1 Studio integration candidate without modifying the source.

Only produces an isolated staged copy. Does not start video processes.
Usage: python stage_studio_patch.py --source rg_studio_ui.py --out-dir temp
"""
from __future__ import annotations

import argparse
import ast
import json
import shutil
from pathlib import Path

CONSTRUCTOR_ANCHOR = "        self._load_batch_ui_state()\n"
TECH_ANCHOR = '        techrow.addWidget(self.tech_toggle);techrow.addWidget(self.audalign_repair_btn);techrow.addStretch();pv.addLayout(techrow)\n'
METHOD_ANCHOR = "    def _montage_tab(self):\n"
QA_ANCHOR = '        passed=bool(result and result.get("passed") and int(code)==0)\n'
STABILITY_MARKER = "RG_STABILITY_V1_STAGED_ATTACH"

METHODS = """    # RG_STABILITY_V1_STAGED_ATTACH - optional, GUI-owned; no worker launches.
    def _rg_stability_attach(self):
        try:
            from rg_stability_v1.rg_studio_adapter import StudioStabilityAdapter
            from PySide6.QtCore import QTimer as _rg_stability_qtimer
            self._rg_stability_adapter = StudioStabilityAdapter(self)
            self._rg_stability_timer = _rg_stability_qtimer(self)
            self._rg_stability_timer.timeout.connect(self._rg_stability_refresh)
            self._rg_stability_timer.start(2500)
            self._rg_stability_refresh()
        except Exception as exc:
            self._rg_stability_adapter = None
            try:self._log("RG_STABILITY_V1|ATTACH_WARNING|"+repr(exc))
            except Exception:pass

    def _rg_stability_refresh(self):
        adapter = getattr(self, "_rg_stability_adapter", None)
        if adapter is not None:
            try:adapter.refresh()
            except Exception as exc:
                try:self._log("RG_STABILITY_V1|REFRESH_WARNING|"+repr(exc))
                except Exception:pass

    def _rg_stability_open_compact(self):
        adapter = getattr(self, "_rg_stability_adapter", None)
        if adapter is None:
            self._rg_stability_attach()
            adapter = getattr(self, "_rg_stability_adapter", None)
        if adapter is not None:
            adapter.show_compact()
        else:
            QMessageBox.warning(self, "RG Stability", "Compact view unavailable")

"""

INIT_HOOK="""        # RG_STABILITY_V1: attach only after Studio has built its GUI.
        QTimer.singleShot(0, self._rg_stability_attach)
"""
TECH_HOOK="""        self._rg_stability_compact_button=_button("MINI PROGRESS")
        self._rg_stability_compact_button.clicked.connect(self._rg_stability_open_compact)
        techrow.addWidget(self._rg_stability_compact_button)
"""
QA_HOOK="""        # RG_STABILITY_V1: fail closed when QA data is malformed or unverified.
        try:
            from rg_stability_v1.rg_stability_readonly import review_qa as _rg_stability_review_qa
            if _rg_stability_review_qa(result or {}).get("status")!="PASS":
                passed=False
        except Exception as _rg_stability_qa_exc:
            passed=False
            try:self._log("RG_STABILITY_V1|QA_GUARD_ERROR|"+repr(_rg_stability_qa_exc))
            except Exception:pass
"""


def create_candidate(source:Path, out_dir:Path)->dict:
    source=Path(source)
    out_dir=Path(out_dir)
    original=source.read_text(encoding="utf-8")
    if STABILITY_MARKER in original:
        raise RuntimeError("ALREADY_PATCHED")
    for anchor in (CONSTRUCTOR_ANCHOR,TECH_ANCHOR,METHOD_ANCHOR,QA_ANCHOR):
        if original.count(anchor)!=1:
            raise RuntimeError("ANCHOR_MISMATCH:"+repr(anchor[:75])+":"+str(original.count(anchor)))
    result=original.replace(CONSTRUCTOR_ANCHOR,CONSTRUCTOR_ANCHOR+INIT_HOOK)
    result=result.replace(TECH_ANCHOR,TECH_HOOK+TECH_ANCHOR)
    result=result.replace(METHOD_ANCHOR,METHODS+METHOD_ANCHOR)
    result=result.replace(QA_ANCHOR,QA_ANCHOR+QA_HOOK)
    ast.parse(result,filename=str(source))
    assert result.count(STABILITY_MARKER)==1
    assert "QTimer.singleShot(0, self._rg_stability_attach)" in result
    assert "rg_stability_readonly import review_qa" in result
    assert result.count("def _rg_stability_open_compact(self):")==1
    assert result.count("def _rg_stability_attach(self):")==1
    out_dir.mkdir(parents=True,exist_ok=True)
    path=out_dir/source.name
    path.write_text(result,encoding="utf-8")
    meta={"schema":"RG_STABILITY_V1_STAGED_PATCH","source":str(source),
          "candidate":str(path),"original_size":len(original.encode("utf-8")),
          "candidate_size":len(result.encode("utf-8")),
          "install_state":"NOT_INSTALLED",
          "requires_idle_studio":True,
          "changes":["GUI mini progress button", "detached compact window", "QA fail-closed gate"],
          "process_launching":False}
    (out_dir/"RG_STABILITY_V1_PATCH_MANIFEST.json").write_text(
        json.dumps(meta,ensure_ascii=True,indent=2),encoding="utf-8")
    return meta


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--source",required=True,type=Path)
    p.add_argument("--out-dir",required=True,type=Path)
    args=p.parse_args()
    print(json.dumps(create_candidate(args.source,args.out_dir),ensure_ascii=True))
