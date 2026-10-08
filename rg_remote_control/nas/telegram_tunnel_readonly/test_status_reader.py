import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import status_reader as r


class StatusReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.p = Path(self.temp.name)
        self.old = r.STATE
        r.STATE = self.p
        self.addCleanup(lambda: setattr(r, "STATE", self.old))

    def write(self, name, content):
        (self.p / name).write_text(content, encoding="utf-8")

    def test_absent_is_unknown(self):
        o = r.overview()
        self.assertIsNone(o["fields"]["telegram_watchdog_status"])
        self.assertIsNone(o["scheduler_heartbeat_age_sec"])
        self.assertIsNone(r.moderation()["watchdog_ok"])

    def test_status_fields_allowlisted(self):
        self.write("telegram_control_plane_status", "OK\n")
        self.assertEqual(r.overview()["fields"]["telegram_control_plane_status"], "OK")
        with self.assertRaises(ValueError):
            r._read_file("../RG_SECRETS/github_token", 200)

    def test_symlinks_denied(self):
        outside = self.p / "secret"
        outside.write_text("secret", encoding="utf-8")
        (self.p / "telegram_watchdog_status").symlink_to(outside)
        self.assertIsNone(r._field("telegram_watchdog_status"))

    def test_credential_redacted(self):
        self.write("rg_telegram_control_app_status", "Bearer some-token-string")
        self.assertEqual(r._field("rg_telegram_control_app_status"), "[REDACTED]")

    def test_watchdog_issue_filter(self):
        self.write("telegram-watchdog-status.json", json.dumps({
            "ok": False, "checkedAt": "2026-10-08T18:00:00Z",
            "issues": ["moderation_unhealthy", "kyiv_alert_queue_stalled", "random_internal_error"],
            "minuteSilence": {"stateDate": "2026-10-08", "ledgerStatus": "uncertain"},
        }))
        self.assertEqual(r.moderation()["issues"], ["moderation_unhealthy"])
        self.assertEqual(r.publications_alerts()["watchdog_issues"], ["kyiv_alert_queue_stalled"])
        self.assertEqual(r.publications_alerts()["minute_silence"]["ledger_status"], "uncertain")

    def test_heartbeat_stale(self):
        self.write("scheduler_last_check_at", "2026-10-08T18:00:00Z")
        os.utime(self.p / "scheduler_last_check_at", (1, 1))
        self.assertFalse(r.scheduler()["nas_scheduler_fresh"])

    def test_large_doc_rejected(self):
        self.write("telegram-watchdog-status.json", "x" * (r.MAX_JSON_BYTES + 1))
        self.assertIsNone(r._watchdog())


if __name__ == "__main__":
    unittest.main()
