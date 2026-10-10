"""Smoke candidate diagnostic gating tests, no model execution or production writes."""
import pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from smoke_candidate_viability_gate_v1 import evaluate

class SmokeCandidateViabilityTests(unittest.TestCase):
    def sample(self):
        return dict(method='synthetic',tested_smoke_regions=7,
                    smoke_regions_with_zero_candidates=0,
                    control_candidate_fraction=0.01,mean_candidate_mask_pixels=5000)
    def test_reference_omission_rejected(self):
        r=evaluate([dict(self.sample(),smoke_regions_with_zero_candidates=4)])[0]
        self.assertIn('VISIBLE_SMOKE_REGION_MISSED',r['reasons'])
        self.assertFalse(r['production_release_allowed'])
    def test_oversized_false_solution_rejected(self):
        r=evaluate([dict(self.sample(),mean_candidate_mask_pixels=83602)])[0]
        self.assertIn('EXCESSIVE_CANDIDATE_AREA',r['reasons'])
    def test_background_bleed_rejected(self):
        r=evaluate([dict(self.sample(),control_candidate_fraction=.59)])[0]
        self.assertIn('BLEED_IN_COARSE_CONTROL_REGIONS',r['reasons'])
    def test_good_synthetic_regions_do_not_approve_production(self):
        r=evaluate([self.sample()])[0]
        self.assertIn('SMOKE_PIXEL_IDENTITY_NOT_VERIFIED',r['reasons'])
        self.assertIn('8865_FULL_NEGATIVE_NOT_VERIFIED',r['reasons'])
        self.assertFalse(r['production_release_allowed'])
    def test_missing_review_regions_rejected(self):
        r=evaluate([dict(self.sample(),tested_smoke_regions=1)])[0]
        self.assertIn('SMOKE_EVIDENCE_CASES_MISSING',r['reasons'])

if __name__=='__main__':unittest.main()
