"""Transactional offline fixture tests; NEVER patch the actual Studio."""
from __future__ import annotations
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import install_v3 as install

def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()

class TransactionalRepairTest(unittest.TestCase):
    def test_backup_install_rollback_and_active_worker_gate(self):
        with tempfile.TemporaryDirectory(prefix="rg_repair_txn_test_") as d:
            base=Path(d);app=base/"APP";program=base/"PROGRAM";candidate=base/"candidate"
            for root in (app,program,candidate):root.mkdir()
            manifest={"version":install.PATCH_VERSION,"files":{}}
            for n in install.FILES:
                original="# OLD "+n+"\n";patched="# NEW "+n+"\n"
                (app/n).write_text(original,encoding="utf-8")
                (candidate/n).write_text(patched,encoding="utf-8")
                manifest["files"][n]={"source_sha256":install.digest(app/n),"candidate_sha256":install.digest(candidate/n)}
                # One installed binary module also exists.
                if n==install.FILES[0]:(program/n).write_text(original,encoding="utf-8")
            (candidate/"RG_REPAIR_REPORT.json").write_text(json.dumps(manifest),encoding="utf-8")
            queue=base/"queue.json"
            queue.write_text(json.dumps({"running":False,"paused":False,"rows":[{"status":"ГОТОВО"}]}),encoding="utf-8")
            backups=base/"backups"
            with patch.object(install,"APP",app),patch.object(install,"INSTALLED",program),patch.object(install,"QUEUE",queue):
                with patch.object(install,"process_blockers",return_value=[{"ProcessId":123}]):
                    with self.assertRaisesRegex(RuntimeError,"STUDIO_OR_VIDEO_WORKERS_RUNNING"):
                        install.apply(candidate,backups)
                self.assertFalse(backups.exists())
                with patch.object(install,"process_blockers",return_value=[]):
                    result=install.apply(candidate,backups)
                    self.assertEqual(result["status"],"INSTALLED")
                    self.assertEqual((app/install.FILES[0]).read_text(encoding="utf-8"),"# NEW "+install.FILES[0]+"\n")
                    report=install.rollback(backups)
                    self.assertEqual(report["status"],"ROLLED_BACK")
                    for n in install.FILES:
                        self.assertEqual((app/n).read_text(encoding="utf-8"),"# OLD "+n+"\n")
                    self.assertEqual((program/install.FILES[0]).read_text(encoding="utf-8"),"# OLD "+install.FILES[0]+"\n")

if __name__=="__main__":unittest.main()
