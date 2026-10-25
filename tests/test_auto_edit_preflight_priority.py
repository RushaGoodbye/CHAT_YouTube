"""Regression tests for safe overnight preflight decision order.

Run: python -m unittest discover -s tests -p 'test_auto_edit_preflight_priority.py'
"""
import ast
import pathlib
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "rg_remote_control" / "auto_edit_features" / "overnight_preflight_v1.py"


def decision(**overrides):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    assignments = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Subscript)
                and isinstance(t.value, ast.Name) and t.value.id == "row"
                and isinstance(t.slice, ast.Constant) and t.slice.value == "night_action"
                for t in n.targets)
    ]
    if len(assignments) != 1:
        raise AssertionError("Expected exactly one night_action assignment")
    expression = ast.Expression(assignments[0].value)
    ast.fix_missing_locations(expression)
    row = {
        "prior_backend_error": False,
        "audio_ambiguous": False,
        "requires_qa_review": False,
        "already_complete": False,
        "inputs_ready": True,
    }
    row.update(overrides)
    return eval(compile(expression, str(SOURCE), "eval"), {"__builtins__": {}}, {"row": row})


class PreflightPriorityTests(unittest.TestCase):
    def test_backend_error_overrides_complete(self):
        self.assertEqual(decision(prior_backend_error=True, already_complete=True), "REVIEW_BACKEND")

    def test_ambiguous_audio_overrides_complete(self):
        self.assertEqual(decision(audio_ambiguous=True, already_complete=True), "REVIEW_AUDIO")

    def test_backend_error_overrides_ambiguous_audio(self):
        self.assertEqual(decision(prior_backend_error=True, audio_ambiguous=True), "REVIEW_BACKEND")

    def test_failed_qa_review(self):
        self.assertEqual(decision(requires_qa_review=True, already_complete=True), "REVIEW_QA")

    def test_verified_complete(self):
        self.assertEqual(decision(already_complete=True), "SKIP_COMPLETE")

    def test_missing_input(self):
        self.assertEqual(decision(inputs_ready=False), "MISSING_INPUT")

    def test_ready(self):
        self.assertEqual(decision(), "RUN_EXPECTED")



class CriticalVsAdvisoryQATests(unittest.TestCase):
    def validator(self):
        tree=ast.parse(SOURCE.read_text(encoding="utf-8"))
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="qa_report_is_valid"]
        self.assertEqual(len(nodes),1)
        env={}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),"exec"),env)
        return env["qa_report_is_valid"]

    def test_advisory_cigarette_warning_does_not_invalidate_xml_release(self):
        valid=self.validator()
        checks=[
            {"name":"Premiere сумісність","ok":True,"critical":True},
            {"name":"Блюр сигарети","ok":False,"critical":False},
            {"name":"Сигарети • детекція/blur","ok":False,"critical":False},
        ]
        self.assertTrue(valid({"passed":True,"checks":checks}))

    def test_any_critical_failure_still_fails(self):
        valid=self.validator()
        for critical in (True,None):
            self.assertFalse(valid({"passed":True,"checks":[
                {"name":"Перевірка XML","ok":False,"critical":critical}
            ]}))

    def test_missing_or_malformed_check_fails_closed(self):
        valid=self.validator()
        self.assertFalse(valid({"passed":True,"checks":[]}))
        self.assertFalse(valid({"passed":True,"checks":[{}]}))
        self.assertFalse(valid({"passed":False,"checks":[{"ok":True}]}))


class XmlGateSourceTests(unittest.TestCase):
    def test_validated_xml_required_for_completion(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        matching = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Subscript)
                    and isinstance(t.value, ast.Name) and t.value.id == "row"
                    and isinstance(t.slice, ast.Constant)
                    and t.slice.value == "complete_manifest" for t in n.targets)
        ]
        self.assertEqual(len(matching), 1)
        expr = ast.unparse(matching[0].value)
        self.assertIn("xml_valid", expr)
        self.assertIn("expected", expr)
        self.assertIn("xml_unique", expr)

    def test_xml_parser_and_sequence_validation_present(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("ET.parse(p).getroot()", source)
        self.assertIn('root_xml.find(".//sequence")', source)
        self.assertIn('sequence.findall("./media/video/track/clipitem")', source)
        self.assertIn('sequence.findall("./media/audio/track/clipitem")', source)

if __name__ == "__main__":
    unittest.main()
