import unittest
from rg_smoking_compliance import ReviewRequired
from rg_smoking_timeline import source_scope,path_identity

TARGET=r'\\server\record\886.mp4'


def timeline(extra='',source='file://server/record/886.mp4'):
    return ('''<xmeml><sequence><duration>120</duration><rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>
    <media><video><track><clipitem id="v1"><start>0</start><end>60</end><in>100</in><out>160</out>
    <file id="source"><pathurl>%s</pathurl></file></clipitem>
    <clipitem id="v2"><start>60</start><end>120</end><in>160</in><out>220</out><file id="source"/>%s</clipitem>
    </track></video></media></sequence></xmeml>'''%(source,extra)).encode()


class TimelineTests(unittest.TestCase):
    def test_reference_resolution_and_exact_union(self):
        r=source_scope(timeline(),TARGET)
        self.assertEqual(r['ranges'],[[100,220]])
        self.assertEqual(r['unique_source_frames'],120)
        self.assertEqual(len(r['clips']),2)

    def test_same_filename_is_not_source_identity(self):
        with self.assertRaisesRegex(ReviewRequired,'EXACT_SOURCE'):
            source_scope(timeline(source='file://different/record/886.mp4'),TARGET)

    def test_conflicting_media_id_blocks(self):
        doc=timeline().replace(b'<file id="source"/>',b'<file id="source"><pathurl>file://other/886.mp4</pathurl></file>')
        with self.assertRaisesRegex(ReviewRequired,'CONFLICTING'): source_scope(doc,TARGET)

    def test_missing_reference_blocks(self):
        with self.assertRaisesRegex(ReviewRequired,'UNRESOLVED'):
            source_scope(timeline().replace(b'<file id="source"/>',b'<file id="unknown"/>'),TARGET)

    def test_timewarp_is_not_one_to_one(self):
        with self.assertRaisesRegex(ReviewRequired,'TIMEWARP'):
            source_scope(timeline().replace(b'<out>220</out>',b'<out>230</out>'),TARGET)
        with self.assertRaisesRegex(ReviewRequired,'TIMEWARP'):
            source_scope(timeline('<filter><effect><effectid>timeremap</effectid></effect></filter>'),TARGET)

    def test_read_only_audit_can_cover_timewarp_source_without_certifying_mapping(self):
        r=source_scope(timeline().replace(b'<out>220</out>',b'<out>230</out>'),TARGET,
            allow_timewarp_for_source_audit=True)
        self.assertEqual(r['ranges'],[[100,230]])
        self.assertFalse(r['exact_timeline_mapping'])
        self.assertEqual(r['purpose'],'SOURCE_AUDIT_ONLY')

    def test_ntsc_cannot_round_into_30fps(self):
        with self.assertRaisesRegex(ReviewRequired,'FRAME_RATE'):
            source_scope(timeline().replace(b'<ntsc>FALSE</ntsc>',b'<ntsc>TRUE</ntsc>'),TARGET)

    def test_transition_sentinel_requires_explicit_resolution(self):
        with self.assertRaisesRegex(ReviewRequired,'BOUNDS'):
            source_scope(timeline().replace(b'<start>60</start>',b'<start>-1</start>'),TARGET)

    def test_uri_percent_escape_and_drive_letter(self):
        self.assertEqual(path_identity('file:///F:/RG%20Data/892.mp4'),path_identity(r'F:\RG Data\892.mp4'))


if __name__=='__main__': unittest.main()
