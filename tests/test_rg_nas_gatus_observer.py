#!/usr/bin/env python3
"""Fully offline regression suite for the read-only NAS Gatus observer."""
import importlib.util
import json
import pathlib
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "rg_remote_control/nas/monitoring/rg_nas_gatus_observer_v1.py"
spec = importlib.util.spec_from_file_location("rg_nas_observer", SOURCE)
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.state = self.root / "RG_NAS_STATE"
        self.state.mkdir()
        self.now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
        self.put("scheduler_last_check_at", self.now.isoformat())
        self.put("scheduler_last_check_status", "OK")
        self.put("telegram_scheduler_components_checked_at", self.now.isoformat())
        self.put("telegram_scheduler_components_status", "OK")
        self.put("RG_CONTROL_CENTER.json", json.dumps(
            {"updated_at": self.now.isoformat(), "status": "ok"}))

    def put(self, name, value):
        (self.state / name).write_text(value, encoding="utf-8")

    def evaluate(self):
        return observer.observe(self.root, now=self.now)

    def test_fresh_all_ok(self):
        self.assertTrue(all(row["success"] for row in self.evaluate().values()))

    def test_stale_scheduler_rejected(self):
        self.put("scheduler_last_check_at", (self.now-timedelta(days=10)).isoformat())
        r = self.evaluate()
        self.assertFalse(r["scheduler"]["success"])
        self.assertTrue(r["control-center"]["success"])

    def test_missing_watchdog_components_telemetry_fails_closed(self):
        (self.state / "telegram_scheduler_components_status").unlink()
        self.assertFalse(self.evaluate()["telegram-components"]["success"])

    def test_non_ok_status_is_rejected(self):
        self.put("scheduler_last_check_status", "RUNNING")
        self.put("telegram_scheduler_components_status", "ERROR")
        self.assertFalse(self.evaluate()["scheduler"]["success"])
        self.assertFalse(self.evaluate()["telegram-components"]["success"])

    def test_control_center_degraded_rejected(self):
        self.put("RG_CONTROL_CENTER.json", json.dumps(
            {"updated_at": self.now.isoformat(), "status": "degraded"}))
        self.assertFalse(self.evaluate()["control-center"]["success"])

    def test_naive_or_future_timestamps_rejected(self):
        self.put("scheduler_last_check_at", "2026-10-25T12:00:00")
        self.assertFalse(self.evaluate()["scheduler"]["success"])
        self.put("scheduler_last_check_at", (self.now+timedelta(minutes=10)).isoformat())
        self.assertFalse(self.evaluate()["scheduler"]["success"])

    def test_malformed_json_is_failure(self):
        self.put("RG_CONTROL_CENTER.json", "{")
        self.assertFalse(self.evaluate()["control-center"]["success"])

    def test_secret_permissions_enforced(self):
        secret = self.root / "token"
        secret.write_text("a"*48, encoding="utf-8")
        secret.chmod(0o644)
        with self.assertRaises(ValueError):
            observer._read_secret(secret)
        secret.chmod(0o600)
        self.assertEqual(observer._read_secret(secret), "a"*48)

    def test_push_rejects_remote_destinations(self):
        with self.assertRaises(ValueError):
            observer.push(self.evaluate(), "https://example.com", "x"*40)

    def test_push_only_local_gatus_and_bearer(self):
        sent = []
        class FakeResponse:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
        def capture(req, timeout):
            sent.append((req.full_url, req.get_header("Authorization"), req.get_method(), timeout))
            return FakeResponse()
        with patch.object(observer, "urlopen", capture):
            observer.push(self.evaluate(), "http://127.0.0.1:18080", "z"*40)
        self.assertEqual(len(sent), 3)
        for url, header, method, timeout in sent:
            self.assertTrue(url.startswith("http://127.0.0.1:18080/api/v1/endpoints/"))
            self.assertEqual(header, "Bearer " + "z"*40)
            self.assertEqual(method, "POST")
            self.assertEqual(timeout, 4)

    def test_main_dryrun_does_not_call_network(self):
        with patch.object(observer, "urlopen", side_effect=AssertionError("network forbidden")):
            self.assertEqual(observer.main(["--root", str(self.root)]), 2)
            # The test clock is older than real time; stale data means exit 2.

if __name__ == "__main__":
    unittest.main(verbosity=2)
