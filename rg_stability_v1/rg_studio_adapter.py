"""RG Stability V1 non-invasive Studio adapter.

Opt-in integration module. Importing it has no side effects.
Never creates QProcesses, touches output files, or triggers background montage.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .rg_compact_progress import CompactProgressWidget
    from .rg_stability_readonly import review_qa
    from .rg_watchdog import WorkerObservation, decide_watchdog
    from .rg_resources import Resources, decide_resources
    from .rg_errors import classify_failure
except ImportError:
    from rg_compact_progress import CompactProgressWidget
    from rg_stability_readonly import review_qa
    from rg_watchdog import WorkerObservation, decide_watchdog
    from rg_resources import Resources, decide_resources
    from rg_errors import classify_failure


def snapshot_from_studio(studio:Any)->dict:
    def label(name,default=""):
        widget=getattr(studio,name,None)
        try:return str(widget.text()).strip()
        except (AttributeError,RuntimeError,TypeError):return default
    pct=label("percent","0").replace("%","").replace(",",".")
    try:progress=max(0.,min(100.,float(pct)))
    except ValueError:progress=0.
    return {
        "stream":label("metric_stream") or label("stream") or "--",
        "progress_percent":progress,
        "stage":label("stage") or label("metric_state") or "IDLE",
        "gpu_percent":getattr(studio,"_last_gpu_pct",None),
        "cpu_percent":getattr(studio,"_last_cpu_pct",None),
        "eta":label("eta","--"),
    }


class StudioStabilityAdapter:
    """A Qt widget and pure decisions, owned by the existing Studio UI."""
    def __init__(self,studio:Any):
        self.studio=studio
        self.compact=CompactProgressWidget(studio)
        self.compact.hide()

    def refresh(self)->dict:
        snapshot=snapshot_from_studio(self.studio)
        self.compact.update_snapshot(snapshot)
        return snapshot

    def show_compact(self):
        self.refresh()
        self.compact.show()

    def hide_compact(self):
        self.compact.hide()

    def inspect_qa(self,report:dict)->dict:
        return review_qa(report)

    def inspect_watchdog(self,obs:WorkerObservation)->dict:
        return decide_watchdog(obs)

    def inspect_resources(self,state:Resources)->dict:
        return decide_resources(state)

    def inspect_error(self,code:str,*,xml_verified:bool,manifest_complete:bool,
                      qa_failure_only:bool=False)->dict:
        return classify_failure(code,xml_verified=xml_verified,
                                manifest_complete=manifest_complete,
                                qa_failure_only=qa_failure_only)
