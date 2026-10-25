#!/usr/bin/env python3
"""Offline contract tests for NAS Telegram scheduler. No real NAS, Docker or Telegram calls."""
import os
import pathlib
import subprocess
import tempfile
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "rg_remote_control/nas/RG_NAS_SCHEDULER_TICK.sh"

class SchedulerOfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rg-nas-scheduler-")
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name)
        self.root = self.base / "nas"
        self.root.mkdir()
        self.state = self.root / "RG_NAS_STATE"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        source = SOURCE.read_text(encoding="utf-8")
        self.assertEqual(source.count('ROOT="/volume1/docker"'), 1)
        self.scheduler = self.base / "scheduler.sh"
        self.scheduler.write_text(source.replace('ROOT="/volume1/docker"', 'ROOT="' + str(self.root) + '"', 1), encoding="utf-8")
        self.put("bin/docker", "exit 1")
        self.put("nas/RG_TELEGRAM_CONTROL_AGENT.sh", "exit 0")
        self.put("nas/RG_NAS_TELEGRAM_WATCHDOG.sh", "exit 0")
        self.put("nas/RG_NAS_TELEGRAM_CONTROL_PLANE.sh", "exit 0")
        self.put("nas/RG_NAS_COMMAND_BUS.sh", "exit 0")
        self.put("nas/RG_NAS_AUTO_DEPLOY.sh", "exit 0")
        self.env = os.environ.copy()
        self.env["PATH"] = str(self.bin) + os.pathsep + self.env["PATH"]

    def put(self, relative, body):
        dest = self.base / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        dest.chmod(0o755)

    def run_scheduler(self, expected_code=0):
        check = subprocess.run(["sh", "-n", str(self.scheduler)], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        proc = subprocess.run(["sh", str(self.scheduler)], env=self.env,
                              capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, expected_code, proc.stdout + proc.stderr)

    def value(self, name):
        return (self.state / name).read_text(encoding="utf-8").strip()

    def test_all_healthy(self):
        self.run_scheduler()
        self.assertEqual(self.value("scheduler_last_check_status"), "OK")
        self.assertEqual(self.value("telegram_scheduler_components_status"), "OK")
        self.assertFalse((self.state / "telegram_scheduler_components_failed").exists())

    def test_failing_watchdog_visible_even_if_deploy_ok(self):
        self.put("nas/RG_NAS_TELEGRAM_WATCHDOG.sh", "exit 27")
        self.run_scheduler()
        self.assertEqual(self.value("scheduler_last_check_status"), "OK")
        self.assertEqual(self.value("telegram_scheduler_components_status"), "ERROR")
        self.assertIn("watchdog", self.value("telegram_scheduler_components_failed"))

    def test_missing_watchdog_cannot_report_healthy(self):
        (self.root / "RG_NAS_TELEGRAM_WATCHDOG.sh").unlink()
        self.run_scheduler()
        self.assertEqual(self.value("telegram_scheduler_components_status"), "ERROR")
        self.assertIn("watchdog_missing", self.value("telegram_scheduler_components_failed"))

    def test_recovery_clears_failure(self):
        self.put("nas/RG_TELEGRAM_CONTROL_AGENT.sh", "exit 3")
        self.run_scheduler()
        self.assertIn("control_agent", self.value("telegram_scheduler_components_failed"))
        self.put("nas/RG_TELEGRAM_CONTROL_AGENT.sh", "exit 0")
        self.run_scheduler()
        self.assertEqual(self.value("telegram_scheduler_components_status"), "OK")
        self.assertFalse((self.state / "telegram_scheduler_components_failed").exists())

    def test_autodeploy_failure_stays_separate(self):
        self.put("nas/RG_NAS_AUTO_DEPLOY.sh", "exit 2")
        self.run_scheduler(expected_code=1)
        self.assertEqual(self.value("scheduler_last_check_status"), "ERROR")
        self.assertEqual(self.value("telegram_scheduler_components_status"), "OK")

    def test_command_bus_runtime_failure_reported(self):
        self.put("nas/RG_NAS_COMMAND_BUS.sh", "exit 23")
        self.run_scheduler()
        self.assertEqual(self.value("nas_command_bus_error"), "command_bus_runtime_error")
        self.assertEqual(self.value("telegram_scheduler_components_status"), "ERROR")
        self.assertIn("command_bus_runtime", self.value("telegram_scheduler_components_failed"))

    def test_command_bus_syntax_failure_reported(self):
        self.put("nas/RG_NAS_COMMAND_BUS.sh", "if then")
        self.run_scheduler()
        self.assertEqual(self.value("nas_command_bus_error"), "command_bus_syntax_error")
        self.assertIn("command_bus_syntax", self.value("telegram_scheduler_components_failed"))

    def test_command_bus_recovery_clears_error(self):
        self.put("nas/RG_NAS_COMMAND_BUS.sh", "exit 7")
        self.run_scheduler()
        self.put("nas/RG_NAS_COMMAND_BUS.sh", "exit 0")
        self.run_scheduler()
        self.assertEqual(self.value("telegram_scheduler_components_status"), "OK")
        self.assertFalse((self.state / "nas_command_bus_error").exists())
        self.assertFalse((self.state / "telegram_scheduler_components_failed").exists())

    def test_no_network_or_publication_invoked(self):
        self.put("bin/curl", "echo unexpected_curl >&2; exit 99")
        self.put("bin/wget", "echo unexpected_wget >&2; exit 99")
        self.run_scheduler()
        self.assertNotIn("unexpected_", self.value("auto-deploy.log") if (self.state / "auto-deploy.log").exists() else "")

if __name__ == "__main__":
    unittest.main(verbosity=2)
