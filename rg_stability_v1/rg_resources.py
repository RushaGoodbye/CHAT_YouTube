"""Read-only resource guard. A low-resource verdict never launches or kills workers."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Resources:
    free_disk_gib: float | None
    free_ram_gib: float | None
    free_vram_gib: float | None
    source_available: bool
    studio_owned: bool

def decide_resources(r:Resources, *, minimum_disk_gib:float=25., minimum_ram_gib:float=3.,
                     minimum_vram_gib:float=2.) -> dict:
    failures=[]
    unknown=[]
    if not r.source_available:failures.append("SOURCE_UNAVAILABLE")
    if not r.studio_owned:failures.append("NOT_STUDIO_OWNED")
    for name,value,limit in (("DISK",r.free_disk_gib,minimum_disk_gib),
                             ("RAM",r.free_ram_gib,minimum_ram_gib),
                             ("VRAM",r.free_vram_gib,minimum_vram_gib)):
        if value is None:unknown.append(name)
        elif value<limit:failures.append(name+"_LOW")
    if failures:
        return {"status":"BLOCK_NEXT_LAUNCH","failures":failures,"unknown":unknown,
                "action":"WARN_AND_PAUSE_AFTER_CURRENT"}
    if unknown:
        return {"status":"REVIEW","failures":[],"unknown":unknown,"action":"COLLECT_METRICS"}
    return {"status":"READY","failures":[],"unknown":[],"action":"NONE"}
