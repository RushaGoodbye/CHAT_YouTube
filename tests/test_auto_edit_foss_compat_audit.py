"""Read-only compatibility audit regression tests. No F: hardware required."""
import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "rg_remote_control" / "auto_edit_features" / "foss_compat_audit_v1.py"
spec = importlib.util.spec_from_file_location("foss_compat_audit_v1", SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class FossProbeTests(unittest.TestCase):
    def test_catalog_contains_safe_first_wave(self):
        self.assertIn("silero-vad", mod.PACKAGES)
        self.assertIn("scenedetect", mod.PACKAGES)
        self.assertIn("torch", mod.PACKAGES)
        self.assertIn("onnxruntime", mod.PACKAGES)

    def test_no_runtime_fails_closed(self):
        with patch.object(mod, "STUDIO", pathlib.Path("/not-existing-rg-studio-xx")), patch.object(
            mod, "RUNTIME", pathlib.Path("/not-existing-rg-runtime-xx")
        ):
            result = mod.probe()
        self.assertEqual(result["status"], "MISSING_RUNTIME")
        self.assertFalse(result["installation_allowed"])
        self.assertFalse(result["model_downloads_allowed"])

    def test_feature_wiring_scan_is_read_only(self):
        with tempfile.TemporaryDirectory() as root:
            app=pathlib.Path(root)
            (app / "a.py").write_text("import mediapipe\n# NO_REFERENCE_FACE\n",encoding="utf-8")
            result=mod.probe_feature_wiring(app)
            self.assertEqual(result["scanned"],1)
            self.assertEqual(result["packages"]["mediapipe"],["a.py"])
            self.assertEqual(result["identity"]["NO_REFERENCE_FACE"],["a.py"])

    def test_probe_is_safe_metadata_only(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn("metadata.version", code)
        self.assertNotIn("pip install", code)
        self.assertNotIn("subprocess.Popen", code)
        self.assertNotIn("urlretrieve", code)
        self.assertNotIn("download_model", code)

if __name__ == "__main__":
    unittest.main()
