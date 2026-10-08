#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Actual Norfair 2.3.0 API smoke before reading user stream evidence."""
from __future__ import annotations
import copy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import norfair_saved_hits_8865 as adapter

a={"t":9630.0,"bbox":[430,510,451,524],
   "score":0.12,"class":"smoking cigarette"}
b={"t":9630.06667,"bbox":[432,510,453,525],
   "score":0.14,"class":"smoking cigarette"}
hits=[a,b]
r=adapter.run_norfair_shadow(hits)
assert r["matched_one_object"] is True, r
assert r["status"]=="CONSISTENT", r
assert len(r["observations"])==2, r
old={"status":"AMBIGUOUS","passed":False,"raw_detection_count":2,
     "rejected_tracks":[{"hits":hits}]}
current={"passed":True,"status":"TRACKED",
         "original_detection_report_sha256":"dummy-hash",
         "confirmed_track_count":1,"tracks":[{"confirmation":"SHORT_STABLE"}]}
qa={"passed":True,"overlay_count":3,"coverage_qa":{"passed":True}}
assert adapter.validate_evidence(old,current,qa,"dummy-hash")==hits
for invalid_old,invalid_current,invalid_qa,invalid_hash in [
    (old,current,qa,"mismatch-hash"),
    (old,current,{"passed":False,"overlay_count":3,"coverage_qa":{"passed":True}},"dummy-hash"),
    ({**old,"raw_detection_count":1},current,qa,"dummy-hash")
]:
    try:
        adapter.validate_evidence(invalid_old,invalid_current,invalid_qa,invalid_hash)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Evidence safety guard failed to reject malformed data")
print("RG_NORFAIR_SYNTHETIC_API_AND_FAIL_CLOSED_TEST: PASS")
