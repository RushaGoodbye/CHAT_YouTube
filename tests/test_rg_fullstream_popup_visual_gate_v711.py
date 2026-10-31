import json
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from rg_fullstream_popup_visual_gate_v711 import classify
# Source of labels: user-supplied before/during/after sheet for RG895.
# A tenth mask at 6000.3–6003.2s is not in the sheet and MUST be pending.
CANDIDATES=[
(1483.3,1490.2,575,480,174,66),
(2520.8,2530.7,744,508,159,94),
(2657.3,2670.2,585,472,150,55),
(2818.8,2826.7,744,508,159,95),
(2865.8,2874.7,585,472,150,55),
(4166.3,4172.7,575,479,173,67),
(6000.3,6003.2,668,513,175,45),
(7402.8,7409.2,775,381,152,69),
(7784.8,7793.7,620,384,307,61),
(7892.8,7895.7,571,509,293,61),
]
def mask(row):
 a,b,x,y,w,h=row
 return {'x':x,'y':y,'width':w,'height':h,'intervals':[[a,b]]}
MASKS=[mask(x) for x in CANDIDATES]
REJECTED=[0,1,2,3,4,5,7,8,9]
REVIEWS=[dict(mask(CANDIDATES[i]),source='editor_visual',status='rejected') for i in REJECTED]

class PopupGateTests(unittest.TestCase):
 def test_visual_sheet_rejects_nine_and_holds_one(self):
  result=classify(MASKS,REVIEWS)
  self.assertEqual(result['approved_count'],0)
  self.assertEqual(result['rejected_indices'],REJECTED)
  self.assertEqual(result['pending_indices'],[6])
  self.assertFalse(result['coverage_verified'])
  self.assertFalse(result['publish_ready'])
 def test_original_two_masks_are_both_rejected(self):
  result=classify([MASKS[8],MASKS[9]],REVIEWS)
  self.assertEqual(result['rejected_indices'],[0,1])
  self.assertEqual(result['approved_count'],0)
 def test_no_editor_review_means_no_blur(self):
  result=classify(MASKS,[])
  self.assertEqual(result['approved_count'],0)
  self.assertEqual(len(result['pending_indices']),10)
 def test_detector_internal_approval_flag_ignored(self):
  m=dict(MASKS[0],approved=True,source='detector',popup_confidence=1)
  self.assertEqual(classify([m],[])['approved_count'],0)
 def test_editor_approval_for_other_time_not_reused(self):
  r=dict(mask(CANDIDATES[0]),source='editor_visual',status='approved')
  self.assertEqual(classify([MASKS[1]],[r])['approved_count'],0)
 def test_explicit_editor_approval_can_select_exact_track(self):
  r=dict(mask(CANDIDATES[6]),source='editor_visual',status='approved')
  q=classify([MASKS[6]],[r])
  self.assertEqual(q['approved_count'],1)
  self.assertFalse(q['coverage_verified'])
 def test_conflicting_reviews_reject(self):
  r=dict(mask(CANDIDATES[0]),source='editor_visual',status='approved')
  q=classify([MASKS[0]],[REVIEWS[0],r])
  self.assertEqual(q['approved_count'],0)
  self.assertEqual(q['rejected_indices'],[0])
 def test_invalid_interval_is_rejected(self):
  m=dict(MASKS[0],intervals=[[10,9]])
  with self.assertRaises(ValueError):classify([m],[])
 def test_invalid_coordinates_are_rejected(self):
  m=dict(MASKS[0],width=-1)
  with self.assertRaises(ValueError):classify([m],[])
 def test_non_editor_review_is_not_evidence(self):
  r=dict(mask(CANDIDATES[0]),source='auto_qa',status='approved')
  self.assertEqual(classify([MASKS[0]],[r])['approved_count'],0)

if __name__=='__main__':unittest.main()
