import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from rg_smoking_stage import patched_gate
from rg_smoking_compliance import ReviewRequired


class StudioPatchTests(unittest.TestCase):
    def test_wrong_baseline_not_patched(self):
        with self.assertRaises(ReviewRequired): patched_gate("VERSION='unrelated'")

    def test_legacy_all_green_reports_cannot_bypass_new_studio_gate(self):
        # Use a minimal old gate with the same actual insertion anchors to
        # check fail-closed composition. Actual installed source is tested on PC.
        text="""from VALIDATE_PREMIERE_XML import validate
VERSION='RG_FINAL_RELEASE_GATE_V2_PRODUCTION'
def evaluate(x,kind='dialogue'):
    failures=[]; checks={}; validate(x)
    if kind=='dialogue':
        checks['legacy_all_passed']=True
    return {'passed':not failures,'failures':failures,'checks':checks}
"""
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'gate.py'; path.write_text(patched_gate(text))
            validator=types.ModuleType('VALIDATE_PREMIERE_XML'); validator.validate=lambda p:True
            with patch.dict(sys.modules,{'VALIDATE_PREMIERE_XML':validator}):
                spec=importlib.util.spec_from_file_location('_synthetic_studio_gate',path)
                module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                result=module.evaluate(Path(td)/'RG_EDITED_892_4.xml')
            self.assertFalse(result['passed'])
            self.assertEqual(result['failures'],['SMOKING_COMPLIANCE_REVIEW_REQUIRED'])
            self.assertIn('FOUR_LAYER_SMOKING_QA_MISSING',result['checks']['smoking_compliance']['failures'])


if __name__=='__main__': unittest.main()
