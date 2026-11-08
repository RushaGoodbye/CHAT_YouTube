from pathlib import Path
import tempfile,json
import unittest
from transactional_install import install,safety_check,RUNTIME_MODULES

SOURCE = """class StudioWindow:
    def __init__(self):
        self._load_batch_ui_state()
    def _montage_tab(self):
        techrow.addWidget(self.tech_toggle);techrow.addWidget(self.audalign_repair_btn);techrow.addStretch();pv.addLayout(techrow)
    def _postrun_finished(self,code,output):
        passed=bool(result and result.get("passed") and int(code)==0)
        return passed
"""

class TransactionalInstallationTests(unittest.TestCase):
    def setup(self,root):
        source=root/"source"/"rg_studio_ui.py"
        installed=root/"installed"/"rg_studio_ui.py"
        source.parent.mkdir()
        installed.parent.mkdir()
        source.write_text(SOURCE,encoding="utf-8")
        installed.write_text(SOURCE,encoding="utf-8")
        queue=root/"queue.json"
        queue.write_text(json.dumps({"queue":["885"],"running":False,
                                     "rows":[{"stream":"885","status":"ГОТОВО"}]}),encoding="utf-8")
        pkg=Path(__file__).resolve().parent
        return source,installed,queue,pkg

    def test_active_workers_and_queued_items_block(self):
        with tempfile.TemporaryDirectory() as temp:
            src,inst,q,pkg=self.setup(Path(temp))
            self.assertFalse(safety_check(source=src,installed=inst,queue_path=q,
                                          active_workers=2,studio_running=False)["safe"])
            q.write_text(json.dumps({"queue":["885"],"running":False,
                                     "rows":[{"stream":"885","status":"ОЧІКУЄ"}]}),encoding="utf-8")
            gate=safety_check(source=src,installed=inst,queue_path=q,
                              active_workers=0,studio_running=False)
            self.assertFalse(gate["safe"])
            self.assertIn("UNFINISHED_QUEUE_ITEMS",gate["problems"])

    def test_check_only_changes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);src,inst,q,pkg=self.setup(root)
            result=install(repo_package=pkg,source=src,installed=inst,queue_path=q,
                           active_workers=0,studio_running=False,backup_root=root/"backups",apply=False)
            self.assertEqual(result["status"],"CHECK_ONLY")
            self.assertEqual(src.read_text(encoding="utf-8"),SOURCE)
            self.assertFalse((src.parent/"rg_stability_v1").exists())

    def test_staged_candidate_install_and_backup_in_sandbox(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);src,inst,q,pkg=self.setup(root)
            result=install(repo_package=pkg,source=src,installed=inst,queue_path=q,
                           active_workers=0,studio_running=False,backup_root=root/"backups",apply=True)
            self.assertEqual(result["status"],"INSTALLED")
            self.assertTrue(result["rollback_available"])
            self.assertEqual(src.read_bytes(),inst.read_bytes())
            self.assertIn("RG_STABILITY_V1_STAGED_ATTACH",src.read_text(encoding="utf-8"))
            for name in RUNTIME_MODULES:
                self.assertTrue((src.parent/"rg_stability_v1"/name).is_file())
            backup=Path(result["backup"])
            self.assertEqual((backup/"SOURCE"/"rg_studio_ui.py").read_text(encoding="utf-8"),SOURCE)
            self.assertEqual((backup/"INSTALLED"/"rg_studio_ui.py").read_text(encoding="utf-8"),SOURCE)

if __name__=="__main__":
    unittest.main()
