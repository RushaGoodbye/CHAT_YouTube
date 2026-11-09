import unittest
from rg_904_noface_scene_policy import SceneEvidence,assess_no_face_scene
class TestNoFaceScenePolicy(unittest.TestCase):
    def make(self,**kwargs):
        d=dict(clock_sec=3978.,matched_sec=3978.5,score=.6367663455,
               peak_over_p75=.02394697,screenshot_decoded=True,
               has_right_guest=False,frame_consistency=True)
        d.update(kwargs)
        return SceneEvidence(**d)
    def test_9043_is_candidate_not_release(self):
        self.assertEqual(assess_no_face_scene(self.make()),(True,"SCENE_CANDIDATE_ONLY_BOUNDARY_QA_REQUIRED"))
    def test_no_bypass_wrong_clock(self):
        self.assertFalse(assess_no_face_scene(self.make(clock_sec=3900))[0])
    def test_no_bypass_weak_scene(self):
        self.assertFalse(assess_no_face_scene(self.make(score=.5))[0])
    def test_no_bypass_low_uniqueness(self):
        self.assertFalse(assess_no_face_scene(self.make(peak_over_p75=.003))[0])
    def test_no_bypass_unverified_frames(self):
        self.assertFalse(assess_no_face_scene(self.make(frame_consistency=False))[0])
    def test_right_guest_uses_original_route(self):
        self.assertFalse(assess_no_face_scene(self.make(has_right_guest=True))[0])
if __name__=="__main__":unittest.main()
