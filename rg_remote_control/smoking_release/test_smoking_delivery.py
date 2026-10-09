"""Synthetic fixtures exercise evidence forgery, XML mapping and audio routing.

They measure software invariants, not smoking detection accuracy.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import cv2
import numpy as np
from rg_smoking_compliance import (LAYERS,SCHEMA,VERSION,ReviewRequired,
    canonical_hash,sha256_file)
from rg_smoking_studio_gate import SCHEMA as DELIVERY_SCHEMA,evaluate_for_xml
from rg_smoking_xml import write_candidate,resolved_audio_hash
from rg_smoking_media import render_candidate


def original_xml(path):
    file='''<file id="original"><name>source.mp4</name><pathurl>%s</pathurl><duration>4</duration>
    <rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate><media><video><samplecharacteristics>
    <width>320</width><height>240</height><pixelaspectratio>square</pixelaspectratio>
    </samplecharacteristics></video><audio><channelcount>2</channelcount></audio></media></file>'''%path.as_uri()
    return ('''<?xml version="1.0"?><!DOCTYPE xmeml><xmeml version="4"><sequence>
    <name>892_4</name><duration>4</duration><rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>
    <media><video><track><clipitem id="v1"><start>0</start><end>4</end><in>0</in><out>4</out>%s
    <filter><effect><effectid>basic</effectid><parameter><parameterid>scale</parameterid><value>135</value></parameter></effect></filter>
    <pproTicksIn>0</pproTicksIn><pproTicksOut>33868800000</pproTicksOut></clipitem></track></video>
    <audio><track><clipitem id="aL"><start>0</start><end>4</end><in>0</in><out>4</out><file id="original"/>
    <sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>
    <filter><effect><effectid>volume</effectid><parameter><value>0.85</value></parameter></effect></filter></clipitem></track>
    <track><clipitem id="aR"><start>0</start><end>4</end><in>0</in><out>4</out><file id="original"/>
    <sourcetrack><mediatype>audio</mediatype><trackindex>2</trackindex></sourcetrack></clipitem></track></audio>
    </media></sequence></xmeml>'''%file).encode()


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.source=self.root/'source.mp4'
        self.render=self.root/'masked.candidate.mov'; self.original=self.root/'original.xml'
        self.xml=self.root/'RG_EDITED_892_4.candidate.xml'
        self.layers={k:np.zeros((240,320),bool) for k in LAYERS}
        for i,k in enumerate(LAYERS): self.layers[k][80+i*10:85+i*10,130:136]=True
        raw=np.random.default_rng(24).integers(0,256,(240,320,3),dtype=np.uint8)
        for path in (self.source,):
            writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),30,(320,240))
            self.assertTrue(writer.isOpened())
            for i in range(4): writer.write(raw)
            writer.release()
        self.original.write_bytes(original_xml(self.source))
        self.scan_path=self.root/'scan.json'; self.review_path=self.root/'review.json'; self.masks=self.root/'masks.npz'
        digest=hashlib.sha256(b''.join(self.layers[k].tobytes() for k in LAYERS)).hexdigest()
        self.scan=dict(schema=SCHEMA,version=VERSION,source_sha256=sha256_file(self.source),
            source_ranges_frames=[[0,4]],dialogue='892_4',inference_completed=True,failures=[],
            source_shape_hw=[240,320],roi_xyxy=[70,30,220,175],
            mask_policy=dict(max_area_fraction=.12,padding_px=3,feather_px=1,blur_sigma=25),
            frames=[dict(source_frame=i,state='CONFIRMED_SMOKING',required={k:True for k in LAYERS},
                layer_pixels={k:int(v.sum()) for k,v in self.layers.items()},mask_sha256=digest,
                local_mask_guard_passed=True,decoded_frame_sha256='d'*64) for i in range(4)])
        cap=cv2.VideoCapture(str(self.source))
        for row in self.scan['frames']:
            ok,image=cap.read(); self.assertTrue(ok)
            row['decoded_frame_sha256']=hashlib.sha256(image.tobytes()).hexdigest()
        cap.release()
        self.save_masks(self.layers)
        self.derivatives=[render_candidate(self.source,self.scan,self.masks,self.render,[0,4])]
        result=write_candidate(self.original,self.derivatives,self.xml,'892_4')
        self.delivery=dict(schema=DELIVERY_SCHEMA,version=VERSION,dialogue='892_4',
            original_xml_path=str(self.original),derivatives=self.derivatives,source_entries=[],**result)
        self.entry=dict(source_path=str(self.source),source_sha256=sha256_file(self.source),
            scan_path=str(self.scan_path),independent_review_path=str(self.review_path),mask_archive_path=str(self.masks))
        self.rebind()

    def save_masks(self,layers):
        np.savez_compressed(self.masks,**{k:np.asarray([np.packbits(v,axis=1)]*4,dtype=np.uint8) for k,v in layers.items()})

    def rebind(self):
        self.scan_path.write_text(json.dumps(self.scan),encoding='utf-8')
        self.review=dict(schema='RG_SMOKING_INDEPENDENT_REVIEW_V1',
            source_sha256=self.scan['source_sha256'],source_ranges_frames=self.scan['source_ranges_frames'],
            scan_sha256=canonical_hash(self.scan),full_timeline_reviewed=True,all_required_layers_covered=True,
            no_visible_smoking_after_blur=True,no_unrelated_object_blur=True,no_flicker=True,
            independent_of_model_predictions=True,reviewer='SYNTHETIC SOFTWARE TEST ONLY')
        self.review_path.write_text(json.dumps(self.review),encoding='utf-8')
        self.entry.update(scan_file_sha256=sha256_file(self.scan_path),review_file_sha256=sha256_file(self.review_path),
            mask_archive_sha256=sha256_file(self.masks))
        self.delivery['source_entries']=[self.entry]
        self.save_delivery()

    def save_delivery(self):
        self.xml.with_name(self.xml.stem+'_SMOKING_COMPLIANCE_QA.json').write_text(json.dumps(self.delivery),encoding='utf-8')

    def gate(self): return evaluate_for_xml(self.xml)

    def test_source_bound_delivery_passes_only_software_fixture(self):
        self.assertTrue(self.gate()['passed'],self.gate())
        self.assertEqual(self.gate()['checked_sources'][0]['reviewed_frames'],4)

    def test_resolved_audio_and_motion_remain_identical(self):
        self.assertEqual(resolved_audio_hash(self.original.read_bytes()),resolved_audio_hash(self.xml.read_bytes()))
        before=ET.fromstring(self.original.read_bytes()); after=ET.fromstring(self.xml.read_bytes())
        self.assertEqual(ET.tostring(before.find('.//video/track/clipitem/filter')),
                         ET.tostring(after.find('.//video/track/clipitem/filter')))
        self.assertIn(self.source.as_uri().encode(),self.xml.read_bytes())
        self.assertIn(self.render.as_uri().encode(),self.xml.read_bytes())

    def test_legacy_pass_boolean_cannot_authorize_delivery(self):
        self.xml.with_name(self.xml.stem+'_SMOKING_COMPLIANCE_QA.json').write_text('{"passed":true,"coverage":1}')
        self.assertIn('FOUR_LAYER_DELIVERY_SCHEMA_INVALID',self.gate()['failures'])

    def test_physical_mask_tamper_blocks_even_with_rebound_file_hash(self):
        changed=copy.deepcopy(self.layers); changed['smoke'][80,130]=True
        self.save_masks(changed); self.entry['mask_archive_sha256']=sha256_file(self.masks); self.save_delivery()
        self.assertIn('PHYSICAL_MASK_IDENTITY_MISMATCH',self.gate()['failures'])

    def test_correct_checksums_cannot_hide_unblurred_encoded_video(self):
        # A separately valid lossless video with no smoking mask must fail even
        # when every editable checksum is refreshed and the codec is correct.
        negative=copy.deepcopy(self.scan)
        for row in negative['frames']: row.update(state='VERIFIED_NEGATIVE',mask_pixels=0)
        zero=self.root/'zero.npz'; np.savez_compressed(zero,**{
            k:np.zeros((4,240,40),np.uint8) for k in LAYERS})
        unblurred=self.root/'unblurred.candidate.mov'
        replacement=render_candidate(self.source,negative,zero,unblurred,[0,4])
        replacement['path']=str(unblurred)
        self.delivery['derivatives']=[replacement]
        self.xml.unlink(); write_candidate(self.original,[replacement],self.xml,'892_4')
        self.delivery['candidate_xml_sha256']=sha256_file(self.xml); self.save_delivery()
        self.assertIn('ENCODED_FRAME_DIFFERS_FROM_VERIFIED_FOUR_LAYER_RENDER',self.gate()['failures'])

    def test_forged_decoded_source_identity_is_rejected(self):
        self.scan['frames'][0]['decoded_frame_sha256']='e'*64; self.rebind()
        self.assertIn('DECODED_SOURCE_FRAME_IDENTITY_MISMATCH',self.gate()['failures'])

    def test_source_change_same_size_blocks(self):
        data=self.source.read_bytes(); self.source.write_bytes(data[:-1]+bytes([data[-1]^1]))
        self.assertIn('SOURCE_MEDIA_CONTENT_CHANGED',self.gate()['failures'])

    def test_audio_edit_blocks_even_when_candidate_hash_updated(self):
        self.xml.write_bytes(self.xml.read_bytes().replace(b'<value>0.85</value>',b'<value>0.80</value>'))
        self.delivery['candidate_xml_sha256']=sha256_file(self.xml); self.save_delivery()
        self.assertIn('AUDIO_TIMELINE_OR_MEDIA_CHANGED',self.gate()['failures'])

    def test_unapproved_camera_edit_blocks_even_after_hash_update(self):
        self.xml.write_bytes(self.xml.read_bytes().replace(b'<value>135</value>',b'<value>145</value>'))
        self.delivery['candidate_xml_sha256']=sha256_file(self.xml); self.save_delivery()
        self.assertIn('CANDIDATE_TIMELINE_DIFFERS_FROM_VERIFIED_REWRITE',self.gate()['failures'])

    def test_no_review_and_dropped_frame_block(self):
        self.review_path.unlink(); self.assertFalse(self.gate()['passed'])
        self.scan['frames'].pop(); self.rebind()
        self.assertIn('TIMELINE_FRAME_COVERAGE_INVALID',self.gate()['failures'])

    def test_negative_preserves_xml_and_has_no_masks(self):
        for row in self.scan['frames']: row.update(state='VERIFIED_NEGATIVE',mask_pixels=0)
        zeros={k:np.zeros((240,320),bool) for k in LAYERS}; self.save_masks(zeros)
        self.xml.write_bytes(self.original.read_bytes())
        self.delivery.update(derivatives=[],candidate_xml_sha256=sha256_file(self.xml)); self.rebind()
        self.assertTrue(self.gate()['passed'],self.gate())
        self.assertEqual(self.original.read_bytes(),self.xml.read_bytes())
        self.save_masks(self.layers); self.entry['mask_archive_sha256']=sha256_file(self.masks); self.save_delivery()
        self.assertIn('NEGATIVE_HAS_PHYSICAL_MASK',self.gate()['failures'])

    def test_quarantine_has_no_override(self):
        quarantined=self.root/'RG_EDITED_886_5.candidate.xml'; quarantined.write_bytes(self.xml.read_bytes())
        self.assertIn('886_5_QUARANTINED_NO_EXPORT',evaluate_for_xml(quarantined)['failures'])
        with self.assertRaisesRegex(ReviewRequired,'QUARANTINED'):
            write_candidate(self.original,self.derivatives,self.root/'other.candidate.xml','886_5')

    def test_malformed_and_outdated_evidence_blocks(self):
        for change in (dict(version='old'),dict(source_entries=[]),dict(source_entries=[None])):
            previous=copy.deepcopy(self.delivery); self.delivery.update(change); self.save_delivery()
            self.assertFalse(self.gate()['passed']); self.delivery=previous

    def test_refuse_source_output_overwrite_and_timing_geometry_mismatch(self):
        with self.assertRaises(ReviewRequired): write_candidate(self.original,self.derivatives,self.xml,'892_4')
        with self.assertRaises(ReviewRequired): write_candidate(self.original,self.derivatives,self.root/'ready.xml','892_4')
        for change in (dict(frames=3),dict(has_audio=True),dict(width=640),dict(source_range_frames=[1,4])):
            d=copy.deepcopy(self.derivatives); d[0].update(change)
            with self.assertRaises(ReviewRequired): write_candidate(self.original,d,self.root/'other.candidate.xml','892_4')


if __name__=='__main__': unittest.main()
