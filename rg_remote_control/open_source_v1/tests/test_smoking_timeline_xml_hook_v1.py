"""Tests for XMEML smoking uncertainty markers; synthetic Premiere XML only."""
import sys
import pathlib
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from rg_smoking_timeline_xml_hook_v1 import mark_xml,MARK_NAME

XML='''<xmeml version="4"><sequence><name>892_1</name><duration>90</duration>
<rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>
<media><video><track>
<clipitem id="v1"><name>892.mp4</name><start>0</start><end>30</end><in>360</in><out>390</out></clipitem>
<clipitem id="v2"><name>892.mp4</name><start>30</start><end>90</end><in>400</in><out>460</out></clipitem>
</track></video>
<audio><track><clipitem id="sound"><name>sound.mp3</name></clipitem></track></audio>
</media><marker><name>USER MARKER</name><in>5</in><out>6</out></marker>
</sequence></xmeml>'''

def section(xml,path):
    if "<!DOCTYPE xmeml>" in xml:
        xml=xml.split("<!DOCTYPE xmeml>",1)[1].strip()
    return ET.tostring(ET.fromstring(xml).find(path))

class TimelineMarkerTests(unittest.TestCase):
    def test_uncertainty_delivered_at_retained_source_time(self):
        rep=[{'uncertain_spans':[{'source_start_sec':12.3,'source_end_sec':12.6,
                                 'reason_codes':['SMOKE_UNVERIFIED']}]}]
        x,s=mark_xml(XML,rep,'892','892_1')
        self.assertEqual(len(s['markers']),1)
        self.assertEqual((s['markers'][0]['start_frame'],s['markers'][0]['end_frame']),(9,18))
        self.assertEqual(s['markers'][0]['start_sec'],.3)
        self.assertFalse(s['low_confidence_blocks_dialogue'])
        self.assertEqual(section(XML,'./sequence/media/audio'),section(x,'./sequence/media/audio'))
        self.assertEqual(section(XML,'./sequence/media/video'),section(x,'./sequence/media/video'))
        self.assertIn('USER MARKER',x)

    def test_cut_intervals_are_not_marked(self):
        report=[{'uncertain_spans':[{'source_start_sec':13.1,'source_end_sec':13.2}]}]
        _,s=mark_xml(XML,report,'892','892_1')
        self.assertEqual(s['markers'],[])

    def test_uncertainty_after_cut_has_correct_new_time(self):
        report=[{'uncertain_spans':[{'source_start_sec':13.5,'source_end_sec':13.9}]}]
        _,s=mark_xml(XML,report,'892','892_1')
        self.assertEqual((s['markers'][0]['start_frame'],s['markers'][0]['end_frame']),(35,47))

    def test_never_merge_across_cut(self):
        report=[{'uncertain_spans':[{'source_start_sec':12,'source_end_sec':14,
                                    'reason_codes':['UNKNOWN_SMOKE']}]}]
        _,s=mark_xml(XML,report,'892','892_1')
        self.assertEqual(len(s['markers']),2)
        self.assertEqual([(x['start_frame'],x['end_frame']) for x in s['markers']],
                         [(0,30),(30,50)])

    def test_rejected_track_hits_become_review_markers(self):
        report=[{'rejected_tracks':[{'hits':[{'t':12.2,'score':.09}]}]}]
        _,s=mark_xml(XML,report,'892','892_1')
        self.assertTrue(s['markers'])

    def test_old_rg_markers_not_duplicated(self):
        report=[{'frames':[{'source_frame':370,'flags':['MOUTH_LANDMARK_UNRELIABLE']}]}]
        x,s=mark_xml(XML,report,'892','892_1')
        x2,s2=mark_xml(x,report,'892','892_1')
        self.assertEqual(len(s['markers']),len(s2['markers']))
        self.assertEqual(x2.count('<marker>'),2)

    def test_wrong_stream_not_annotated(self):
        report=[{'uncertain_spans':[{'source_start_sec':12.1,'source_end_sec':12.5,
                                    'source_key':'886'}]}]
        _,s=mark_xml(XML,report,'892','892_1')
        self.assertEqual(len(s['markers']),0)

    def test_unknown_source_time_reported_no_fabrication(self):
        report=[{'unconfirmed_detection_count':3}]
        _,s=mark_xml(XML,report,'892','892_1')
        self.assertEqual(len(s['markers']),0)
        self.assertIn('AI_EVENTS_WITHOUT_SOURCE_TIMECODE',s['warning_codes'])

    def test_retimed_clip_not_guessed(self):
        raw=XML.replace('<end>30</end><in>360</in><out>390</out>',
                        '<end>30</end><in>360</in><out>400</out>')
        report=[{'uncertain_spans':[{'source_start_sec':12.3,'source_end_sec':12.6}]}]
        _,s=mark_xml(raw,report,'892','892_1')
        self.assertEqual(len(s['markers']),0)

    def test_bad_xml_rejected_as_technical_issue(self):
        with self.assertRaises(ValueError):
            mark_xml('<broken/>',[], '892','892_1')

if __name__=='__main__':
    unittest.main()
