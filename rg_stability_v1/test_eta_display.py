from datetime import datetime,timezone
import unittest
from rg_eta_display import display_eta,UNKNOWN

class ETAResults(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,8,20,0,tzinfo=timezone.utc)
    def test_backend_estimate(self):
        r=display_eta(backend_remaining=3600,queue_text="~ 25 хв",now=self.now)
        self.assertEqual(r["source"],"backend")
        self.assertEqual(r["remaining_seconds"],3600)
        self.assertIn("21:00",r["text"])
    def test_queue_estimate_not_erased(self):
        r=display_eta(backend_remaining=None,queue_text="~ 25 хв",now=self.now)
        self.assertEqual(r["source"],"queue")
        self.assertEqual(r["remaining_seconds"],1500)
        self.assertNotIn("—",r["text"])
    def test_missing_estimate_informative(self):
        r=display_eta(backend_remaining=None,queue_text="—",now=self.now)
        self.assertEqual(r["text"],UNKNOWN)
        self.assertIsNone(r["finish_at"])
    def test_reject_unsafe_values(self):
        for x in (float("nan"),-5,float("inf"),8*24*3600,True):
            self.assertEqual(display_eta(backend_remaining=x,queue_text="~ 10 хв",now=self.now)["source"],"queue")
    def test_formats(self):
        self.assertEqual(display_eta(queue_text="01:25:00")["remaining_seconds"],5100)
        self.assertEqual(display_eta(queue_text="25:00")["remaining_seconds"],1500)
        self.assertEqual(display_eta(queue_text="2 год 15 хв")["remaining_seconds"],8100)

if __name__=="__main__":
    unittest.main()
