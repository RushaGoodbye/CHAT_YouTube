"""Inject an ETA fallback into an isolated Studio UI candidate only.

This code never writes to live Studio and never launches worker processes.
"""
from __future__ import annotations
from pathlib import Path
import ast

OLD='''                if rem is None:
                    eta_text="—"
                else:
'''
NEW='''                if rem is None:
                    # Prefer a valid queue estimate; never overwrite with a dash.
                    from rg_stability_v1.rg_eta_display import display_eta as _rg_eta_display
                    _rg_eta_queue = None
                    _rg_eta_index = getattr(self, "_batch_current_index", None)
                    if (_rg_eta_index is not None and
                            hasattr(self, "batch_table") and
                            0 <= _rg_eta_index < self.batch_table.rowCount()):
                        _rg_eta_item = self.batch_table.item(_rg_eta_index, 5)
                        _rg_eta_queue = _rg_eta_item.text() if _rg_eta_item else None
                    _rg_eta_result = _rg_eta_display(queue_text=_rg_eta_queue)
                    eta_text = _rg_eta_result["text"]
                else:
'''
MARKER="_rg_eta_result"

def apply_eta_patch(source:str)->str:
    if MARKER in source:raise RuntimeError("ETA_PATCH_ALREADY_APPLIED")
    if source.count(OLD)!=1:
        raise RuntimeError("ETA_PLACEHOLDER_ANCHOR_MISSING_OR_AMBIGUOUS")
    updated=source.replace(OLD,NEW)
    ast.parse(updated)
    assert "eta_text = _rg_eta_result" in updated
    return updated

def stage_eta_candidate(source_path:Path,out_path:Path)->dict:
    source_path=Path(source_path)
    out_path=Path(out_path)
    patched=apply_eta_patch(source_path.read_text(encoding="utf-8"))
    out_path.parent.mkdir(parents=True,exist_ok=True)
    out_path.write_text(patched,encoding="utf-8")
    return {"status":"STAGED_NOT_INSTALLED","path":str(out_path),
            "active_studio_modified":False}
