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

if __name__ == "__main__":
    unittest.main()
