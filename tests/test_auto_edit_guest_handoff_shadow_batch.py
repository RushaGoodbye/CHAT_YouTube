import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"rg_remote_control"/"auto_edit_features"/"guest_handoff_shadow_batch_v1.py"
spec=importlib.util.spec_from_file_location("guest_handoff_shadow",SCRIPT)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

XML1="""<xmeml><sequence><media><video><track>
<clipitem><name>stream.mp4</name><masterclipid>masterclip-video</masterclipid><in>167719</in><out>167920</out>
<file><pathurl>file:///F:/RG/stream.mp4</pathurl></file></clipitem></track></video>
<audio><track><clipitem><in>169922</in><out>170123</out><file>
<pathurl>file:///F:/RG/audio.wav</pathurl></file></clipitem></track></audio></media></sequence></xmeml>"""

class GuestHandoffShadowTests(unittest.TestCase):
    def test_media_path_windows_drive_decoding(self):
        self.assertEqual(str(m.local_media_path("file:///F:/RG%20TEST/source.mp4")),
                         r"F:\RG TEST\source.mp4")
        self.assertIsNone(m.local_media_path("https://test.invalid/media.mp4"))

    def test_source_intervals(self):
        with tempfile.TemporaryDirectory() as d:
            xml=Path(d)/"clip.xml"
            xml.write_text(XML1,encoding="utf-8")
            self.assertEqual(m.intervals_from_xml(xml,"video"),(167719,167920))
            self.assertEqual(m.intervals_from_xml(xml,"audio"),(169922,170123))

    def test_sample_window_bounded_and_dense_small_overlap(self):
        times=m.sample_times(5588.,5595.,1.4)
        self.assertGreaterEqual(len(times),5)
        self.assertEqual(times[0],5588.)
        self.assertEqual(times[-1],5595.)
        self.assertLessEqual(len(m.sample_times(0.,999999.,1.)),24)

    def test_all_three_controlled_handoffs_only(self):
        self.assertEqual({(a,b,c) for a,b,c,*_ in m.CASES},
                         {("901",4,5),("901",5,6),("905",1,2)})

    def test_source_never_changes_xml_and_logs_no_embedded_media(self):
        txt=SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"auto_trim":False',txt)
        self.assertIn('"xml_writes":0',txt)
        self.assertIn('"media_writes":0',txt)
        self.assertNotIn("write_text(",txt)
        self.assertNotIn("torch.hub",txt)
        self.assertNotIn("unlink(",txt)

if __name__=="__main__":
    unittest.main()
