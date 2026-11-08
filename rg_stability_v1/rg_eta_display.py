"""ETA display arbitration: backend estimate, queue estimate, then explicit warm-up.

Pure functions: never launch or interrupt Studio workers.
"""
from __future__ import annotations
from datetime import datetime, timedelta
import math
import re

UNKNOWN = "Оцінка часу уточнюється"
def _valid_seconds(value):
    try:
        if value is None or isinstance(value,bool):return None
        x=float(value)
        if not math.isfinite(x) or x<0 or x>7*24*3600:return None
        return int(round(x))
    except (TypeError,ValueError,OverflowError):return None

def _from_queue_text(value):
    value=str(value or "").strip().lower()
    if not value or value in {"—","-","--","unknown","n/a"}:return None
    clock=re.fullmatch(r"(\d{1,3}):(\d{2})(?::(\d{2}))?",value)
    if clock:
        a,b,c=clock.groups()
        if c is None:return int(a)*60+int(b)
        return int(a)*3600+int(b)*60+int(c)
    h=re.search(r"(\d+)\s*(?:год|час|hour|h\b)",value)
    m=re.search(r"(\d+)\s*(?:хв|мин|minute|min\b)",value)
    if h or m:return int(h.group(1) if h else 0)*3600+int(m.group(1) if m else 0)*60
    return None

def display_eta(*, backend_remaining=None, queue_text=None, elapsed_seconds=None,
                progress_percent=None, now=None):
    seconds=_valid_seconds(backend_remaining)
    origin="backend"
    if seconds is None:
        seconds=_valid_seconds(_from_queue_text(queue_text))
        origin="queue"
    if seconds is None:
        return {"text":UNKNOWN,"remaining_seconds":None,"finish_at":None,
                "confidence":"unknown","source":"warming","informative":True}
    hours,rest=divmod(seconds,3600)
    minutes=rest//60
    if hours:
        label=f"~ {hours} год {minutes:02d} хв"
    else:
        label=f"~ {max(1,math.ceil(seconds/60))} хв" if seconds else "Менше хвилини"
    now=now or datetime.now().astimezone()
    finish=(now+timedelta(seconds=seconds)).strftime("%H:%M")
    return {"text":f"{label} · до {finish}","remaining_seconds":seconds,
            "finish_at":finish,"confidence":"estimate","source":origin,"informative":True}
