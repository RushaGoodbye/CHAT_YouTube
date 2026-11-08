"""Pure policy decisions for a Studio-owned watchdog. No process killing."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional

@dataclass(frozen=True)
class WorkerObservation:
    running: bool
    now: float
    last_progress_at: float
    last_heartbeat_at: float
    last_output_at: float
    stage: str = ""
    cpu_percent: Optional[float] = None
    gpu_percent: Optional[float] = None

def decide_watchdog(obs:WorkerObservation, *, warn_seconds:int=300, stall_seconds:int=900)->dict:
    if not obs.running:
        return {"status":"IDLE","action":"NONE","reason":"No active Studio worker"}
    timestamps=[float(x) for x in (obs.last_progress_at,obs.last_heartbeat_at,obs.last_output_at) if x is not None]
    if not timestamps or any(x>obs.now+3 for x in timestamps):
        return {"status":"UNKNOWN","action":"OBSERVE","reason":"Invalid or missing activity timestamps"}
    silence=max(0.,obs.now-max(timestamps))
    if silence>=stall_seconds:
        # Never kill or retry on an inferred hang. Preserve outputs and request review.
        return {"status":"SUSPECTED_STALL","action":"FLAG_FOR_STUDIO_REVIEW",
                "silent_seconds":round(silence),"reason":"No heartbeat, progress or output activity"}
    if silence>=warn_seconds:
        return {"status":"SLOW","action":"OBSERVE","silent_seconds":round(silence),
                "reason":"Stage is active but no recent signal"}
    return {"status":"ACTIVE","action":"NONE","silent_seconds":round(silence),
            "reason":"Recent process activity"}
