from __future__ import annotations
import json, os, time
from pathlib import Path

DATA = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
p = DATA / "updater_smoke_020201.json"
tmp = p.with_suffix(".tmp")
tmp.write_text(json.dumps({
    "schema": "RG_UPDATER_SMOKE_V1",
    "version": "0.20.20.1",
    "ts": time.time()
}, ensure_ascii=False, indent=2), encoding="utf-8")
os.replace(tmp, p)
print("RG_UPDATER_SMOKE|PASS|0.20.20.1", flush=True)
