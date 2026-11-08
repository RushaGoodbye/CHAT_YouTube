import unittest
from stage_eta_ui_patch import apply_eta_patch

class ETAUiPatch(unittest.TestCase):
    def test_only_eta_placeholder_replaced(self):
        original = '''class T:
    def on_data(self, rem):
                if rem is None:
                    eta_text="—"
                else:
                    eta_text="42"
                return eta_text
'''
        fixed=apply_eta_patch(original)
        self.assertIn('eta_text = _rg_eta_result["text"]',fixed)
        self.assertIn('self.batch_table.item(_rg_eta_index, 5)',fixed)
        self.assertNotIn('eta_text="—"',fixed)
    def test_fail_closed_without_anchor(self):
        with self.assertRaises(RuntimeError):apply_eta_patch("class App: pass")

if __name__=="__main__":
    unittest.main()
