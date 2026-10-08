#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Synthetic real-image motion regression before running 886 sample."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import numpy as np
import cv2
from norfair_real_motion_8865_v1 import match_track,norfair_probe,clamp_bbox

rng=np.random.default_rng(886)
patch=rng.integers(35,230,size=(18,25),dtype=np.uint8)
images=[]
for k in range(17):
    img=np.full((160,250),9,dtype=np.uint8)
    x=80+k*2;y=85+k
    img[y:y+18,x:x+25]=patch
    images.append(cv2.cvtColor(img,cv2.COLOR_GRAY2BGR))
index=8
bbox=[80+index*2,85+index,80+index*2+25,85+index+18]
t=match_track(images,bbox,index)
assert t["frame_count"]==17,t
assert t["matched_frames"]>=14,t
assert t["template_textured"] is True,t
assert t["matched_frames"]<=17
n=norfair_probe(t)
assert n["one_id_continuity"] is True,n
assert n["distinct_confirmed_track_ids"]==1,n
try:
    match_track(images,[15,15,16,16],index)
except RuntimeError:
    pass
else:
    raise AssertionError("Tiny seed patch was not rejected")
print("RG_OSS_NORFAIR_REAL_FRAME_SYNTHETIC_GATE: PASS")
