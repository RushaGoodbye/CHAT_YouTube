import copy
from pathlib import Path
import tempfile
import unittest

import numpy as np

from rg_smoking_compliance import (LAYERS, SCHEMA, VERSION, MaskPolicy,
    ReviewRequired, blur_frame, cache_key, canonical_hash, compose_masks,
    evaluate_scan, sha256_file, validate_ranges)


class MaskTests(unittest.TestCase):
    def setUp(self):
        self.shape = (240, 320)
        self.masks = {k: np.zeros(self.shape, bool) for k in LAYERS}
        # Four separate known targets; the cigarette is only one pixel wide.
        self.masks['cigarette'][96:104, 130] = True
        self.masks['grip'][106:113, 132:145] = True
        self.masks['smoke'][80:87, 120:124] = True
        self.masks['mouth'][102:109, 148:164] = True
        self.required = {k: True for k in LAYERS}
        self.policy = MaskPolicy(max_area_fraction=.12, padding_px=3, feather_px=1)
        self.roi = (70, 30, 220, 175)

    def compose(self, **kw):
        return compose_masks(self.masks, self.required, self.shape, self.roi,
                             policy=self.policy, **kw)

    def test_thin_cigarette_gets_full_opacity_with_soft_boundary(self):
        alpha, metrics = self.compose()
        for mask in self.masks.values():
            self.assertTrue((alpha[mask] == 1).all())
        self.assertTrue(((alpha > 0) & (alpha < 1)).any())
        self.assertLess(metrics['mask_area_fraction'], .12)

    def test_blur_preserves_every_pixel_outside_mask(self):
        frame = np.random.default_rng(11).integers(0, 256, (*self.shape, 3), dtype=np.uint8)
        alpha, _ = self.compose()
        out = blur_frame(frame, alpha, self.policy)
        self.assertTrue(np.array_equal(out[alpha == 0], frame[alpha == 0]))
        core = np.logical_or.reduce(list(self.masks.values()))
        self.assertLess(out[core].std(), frame[core].std() * .2)

    def test_every_missing_required_layer_blocks(self):
        for key in LAYERS:
            with self.subTest(key=key):
                original = self.masks[key]
                self.masks[key] = np.zeros(self.shape, bool)
                with self.assertRaisesRegex(ReviewRequired, 'REQUIRED_MASK_MISSING'):
                    self.compose()
                self.masks[key] = original

    def test_unknown_presence_is_not_treated_as_absent(self):
        self.required['smoke'] = None
        with self.assertRaisesRegex(ReviewRequired, 'OBSERVATION_UNKNOWN'):
            self.compose()

    def test_microphone_region_conflict_blocks_without_removing_pixels(self):
        mic = np.zeros(self.shape, bool)
        mic[106:115, 130:150] = True
        with self.assertRaisesRegex(ReviewRequired, 'UNRELATED_OBJECT_OVERLAP'):
            self.compose(forbidden=mic)

    def test_collateral_from_feather_also_blocks(self):
        mic = np.zeros(self.shape, bool)
        mic[76:80, 120:124] = True
        with self.assertRaisesRegex(ReviewRequired, 'UNRELATED_OBJECT'):
            self.compose(forbidden=mic)

    def test_out_of_roi_is_rejected_not_clipped(self):
        self.masks['smoke'][25, 110] = True
        with self.assertRaisesRegex(ReviewRequired, 'OUTSIDE_LOCAL_ROI'):
            self.compose()

    def test_nonbinary_nan_wrong_shape_and_full_frame_are_rejected(self):
        for value in (np.full(self.shape, 127, np.uint8),
                      np.full(self.shape, np.nan), np.zeros((10, 10), bool),
                      np.ones(self.shape, bool)):
            with self.subTest(shape=value.shape):
                self.masks['smoke'] = value
                with self.assertRaises(ReviewRequired):
                    self.compose()


class GateTests(unittest.TestCase):
    def setUp(self):
        self.sha = 'a' * 64
        self.ranges = [[360, 363], [370, 372]]
        self.scan = dict(schema=SCHEMA, version=VERSION, source_sha256=self.sha,
            source_ranges_frames=self.ranges, dialogue='892_4', inference_completed=True,
            failures=[], frames=[dict(source_frame=n, state='CONFIRMED_SMOKING',
                required={k: True for k in LAYERS}, layer_pixels={k: 20 for k in LAYERS},
                local_mask_guard_passed=True, mask_sha256='b' * 64)
                for a, b in self.ranges for n in range(a, b)])

    def review(self):
        return dict(schema='RG_SMOKING_INDEPENDENT_REVIEW_V1', source_sha256=self.sha,
            source_ranges_frames=self.ranges, scan_sha256=canonical_hash(self.scan),
            full_timeline_reviewed=True, all_required_layers_covered=True,
            no_visible_smoking_after_blur=True, no_unrelated_object_blur=True,
            no_flicker=True, independent_of_model_predictions=True,
            reviewer='Independent test reviewer; synthetic fixture only')

    def gate(self, review=True, dialogue='892_4', sha=None):
        return evaluate_scan(self.scan, source_sha256=sha or self.sha,
            ranges=self.ranges, dialogue=dialogue,
            independent_review=self.review() if review else None)

    def test_complete_separate_review_passes_exact_scope_only(self):
        self.assertTrue(self.gate()['passed'])
        self.assertFalse(self.gate(sha='f' * 64)['passed'])
        self.assertFalse(self.gate(dialogue='892_5')['passed'])

    def test_geometry_and_model_scores_never_replace_independent_review(self):
        self.scan.update(confidence=1., warnings=0, passed=True, production_release_allowed=True)
        r = self.gate(review=False)
        self.assertFalse(r['release_allowed'])
        self.assertIn('INDEPENDENT_VISUAL_REVIEW_MISSING', r['failures'])

    def test_zero_detection_does_not_certify_negative(self):
        for row in self.scan['frames']:
            row.update(state='NO_SMOKING_DETECTED', mask_pixels=0)
        self.assertIn('AMBIGUOUS_OR_LOST_TRACK', self.gate()['failures'])

    def test_one_dropped_reordered_duplicate_or_extra_frame_blocks(self):
        original = copy.deepcopy(self.scan['frames'])
        variants = [original[:-1], original[::-1], original[:1] + original,
                    original + [dict(original[-1], source_frame=373)]]
        for rows in variants:
            self.scan['frames'] = rows
            self.assertIn('TIMELINE_FRAME_COVERAGE_INVALID', self.gate()['failures'])

    def test_missing_smoke_track_loss_and_strings_cannot_pass(self):
        row = self.scan['frames'][0]
        row['layer_pixels']['smoke'] = 0
        self.assertFalse(self.gate()['passed'])
        row['layer_pixels']['smoke'] = 20
        row['state'] = 'TRACK_LOST'
        self.assertFalse(self.gate()['passed'])
        row['state'] = 'CONFIRMED_SMOKING'
        row['required']['smoke'] = 'false'
        self.assertFalse(self.gate()['passed'])

    def test_quarantine_is_dialogue_specific_and_never_overridden(self):
        self.scan['dialogue'] = '886_5'
        self.assertIn('886_5_QUARANTINED_NO_EXPORT', self.gate(dialogue='886_5')['failures'])
        self.scan['dialogue'] = '886_6'
        self.assertTrue(self.gate(dialogue='886_6')['passed'])

    def test_old_review_invalid_after_mask_change(self):
        review = self.review()
        self.scan['frames'][0]['mask_sha256'] = 'c' * 64
        result = evaluate_scan(self.scan, source_sha256=self.sha, ranges=self.ranges,
            dialogue='892_4', independent_review=review)
        self.assertIn('REVIEW_SOURCE_OR_MASKS_MISMATCH', result['failures'])

    def test_unknown_empty_and_malformed_results_fail_closed(self):
        for scan in ({}, None, dict(self.scan, frames=[]), dict(self.scan, frames=[None])):
            result = evaluate_scan(scan, source_sha256=self.sha, ranges=self.ranges,
                dialogue='892_4', independent_review=self.review())
            self.assertFalse(result['passed'])

    def test_bad_ranges_and_invalid_sha_are_rejected(self):
        for ranges in ([], [[0, 1], [0, 2]], [[2, 1]], [[True, 2]], [[0., 1.]], [[-1, 3]]):
            with self.assertRaises(ReviewRequired):
                validate_ranges(ranges)
        self.assertFalse(self.gate(sha='g' * 64)['passed'])

    def test_cache_changes_with_content_models_scope_and_parameters(self):
        args = dict(source_sha256=self.sha, ranges=self.ranges,
            model_hashes={'sam2': 'b' * 64}, options={'blur_sigma': 25}, dialogue='892_4')
        old = cache_key(**args)
        for change in ({'source_sha256': 'c' * 64}, {'model_hashes': {'sam2': 'd' * 64}},
                       {'ranges': [[360, 364]]}, {'options': {'blur_sigma': 26}}, {'dialogue': '892_5'}):
            self.assertNotEqual(old, cache_key(**dict(args, **change)))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'source.bin'
            path.write_bytes(b'abc')
            before = sha256_file(path)
            path.write_bytes(b'xyz')
            self.assertNotEqual(before, sha256_file(path))


if __name__ == '__main__':
    unittest.main(verbosity=2)
