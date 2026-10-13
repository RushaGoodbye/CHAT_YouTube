#!/usr/bin/env python3
"""Pure QA-contract regressions; no NAS, UI, GPU, or production artifacts touched."""
import ast
from pathlib import Path
import unittest

SOURCE=Path(__file__).with_name("overnight_preflight_v1.py")

def load_predicate():
    tree=ast.parse(SOURCE.read_text(encoding="utf-8"))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="qa_report_is_valid")
    module=ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[]))
    namespace={}
    exec(compile(module,str(SOURCE),"exec"),namespace)
    return namespace["qa_report_is_valid"]

class PostrunQAGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.accept=staticmethod(load_predicate())

    def test_all_explicitly_passed(self):
        self.assertTrue(self.accept({"passed":True,"checks":[{"name":"audio","ok":True},{"name":"xml","ok":True}]}))

    def test_rejects_false_green(self):
        self.assertFalse(self.accept({"passed":True,"checks":[{"name":"audio","ok":False}]}))

    def test_rejects_missing_or_empty_checks(self):
        for checks in (None,[],{},["broken"],[{}], [{"ok":1}], [{"ok":"true"}]):
            with self.subTest(checks=checks):
                self.assertFalse(self.accept({"passed":True,"checks":checks}))

    def test_rejects_missing_malformed_or_failed_report(self):
        for report in (None,{},[],{"passed":False,"checks":[{"ok":True}]},
                       {"passed":1,"checks":[{"ok":True}]},
                       {"passed":True}, {"passed":True,"checks":[{"ok":True},None]}):
            with self.subTest(report=report):
                self.assertFalse(self.accept(report))

if __name__=="__main__":
    unittest.main()
