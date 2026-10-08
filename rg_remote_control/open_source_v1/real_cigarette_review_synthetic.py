#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-test of the real-frame review montage geometry. No real stream access."""
from __future__ import annotations
import os
import sys
import tempfile
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from real_cigarette_review_8865_v1 import make_tile,contact_sheets,CELL_H,CELL_W

frames=[]
for i in range(6):
    frame=np.full((1080,1920,3),30,dtype=np.uint8)
    frame[520:540,435+i:468+i]=(35,100,220)
    frames.append(frame)
originals=[f.copy() for f in frames]
hint=[435,520,468,540]
tile=make_tile(frames[0],hint,1,9559.0)
assert tile.shape==(CELL_H,CELL_W,3),tile.shape
assert np.array_equal(frames[0],originals[0]),"Source frame modified"
with tempfile.TemporaryDirectory() as td:
    paths=contact_sheets(frames,hint,9559.0,Path(td))
    assert len(paths)==1,paths
    assert paths[0].stat().st_size>10000,paths[0].stat().st_size
    assert all(np.array_equal(a,b) for a,b in zip(frames,originals))
try:
    make_tile(np.zeros((1080,1280,3),dtype=np.uint8),hint,1,0.0)
except RuntimeError as err:
    assert "geometry" in str(err)
else:
    raise AssertionError("Incorrect video resolution accepted")
print("RG_REAL_CIGARETTE_REVIEW_SHEET_LAYOUT_AND_SOURCE_IMMUTABILITY: PASS")
