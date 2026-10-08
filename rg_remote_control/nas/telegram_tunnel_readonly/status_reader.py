"""Read-only, fixed-field Synology Telegram status reader.

No arbitrary paths, shell commands, network requests or writes. Mount only
/volume1/docker/RG_NAS_STATE to /state:ro. Missing data is UNKNOWN.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import re
import stat
from pathlib import Path
from zoneinfo import ZoneInfo

STATE = Path(os.environ.get("RG_TELEGRAM_STATE_DIR", "/state"))
TZ = ZoneInfo("Europe/Kyiv")
MAX_TEXT = 400
MAX_JSON_BYTES = 128 * 1024

FIELDS = {
    "telegram_control_plane_status",
    "telegram_control_plane_last_sync_at",
    "telegram_watchdog_status",
    "telegram_watchdog_admin_fetch_status",
    "rg_telegram_control_app_status",
    "rg_telegram_control_app_version",
    "rg_telegram_control_app_deployed_at",
    "rg_telegram_control_agent_last_run_at",
    "rg_telegram_control_agent_last_action",
    "rg_telegram_control_agent_last_rc",
    "scheduler_last_check_status",
    "last_check_status",
    "last_deploy_status",
    "last_deployed_at",
    "deploy_stage",
    "mcp_deploy_status",
    "telegram_startup_selftest_status",
    "live_smoke_status",
    "minute_silence_watchdog_date",
    "minute_silence_watchdog_ok_date",
    "telegram_command_bus_phase",
    "telegram_command_bus_result_status",
    "telegram_command_bus_rc",
    "telegram_command_bus_seen_action",
}
HEARTBEATS = {
    "scheduler_last_check_at",
    "mcp_tick_heartbeat_at",
    "rg_telegram_control_agent_last_run_at",
    "telegram_control_plane_last_sync_at",
    "failover_heartbeat_at",
}
JSON_FILES = {"telegram-watchdog-status.json"}
SAFE_SCALAR = re.compile(r"^[-a-zA-Z0-9 _.,:+/]{0,400}$")
SENSITIVE = re.compile(r"(sk-[a-zA-Z0-9_-]{8,}|gh[pousr]_[a-zA-Z0-9_]{8,}|bearer\s+\S+|password|token|secret|authorization)", re.I)


def _read_file(name: str, max_bytes: int) -> str | None:
    if name not in FIELDS | HEARTBEATS | JSON_FILES:
        raise ValueError("File is not in fixed allowlist")
    # Prevent traversal, symlink jumps, and nonregular pseudo-files.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(STATE / name, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
                return None
            data = os.read(fd, max_bytes + 1)
            if len(data) > max_bytes:
                return None
            return data.decode("utf-8", "replace").strip()
        finally:
            os.close(fd)
    except (OSError, ValueError):
        return None


def _field(name: str) -> str | None:
    value = _read_file(name, MAX_TEXT)
    if value is None or not value or len(value) > MAX_TEXT:
        return None
    # Prevent raw logs and possible credentials from being exposed.
    if SENSITIVE.search(value) or not SAFE_SCALAR.fullmatch(value):
        return "[REDACTED]"
    return value


def _age_seconds(name: str) -> int | None:
    if name not in HEARTBEATS:
        raise ValueError("Non-heartbeat field")
    try:
        s = os.stat(STATE / name, follow_symlinks=False)
        if not stat.S_ISREG(s.st_mode):
            return None
        return max(0, int(dt.datetime.now(dt.timezone.utc).timestamp() - s.st_mtime))
    except OSError:
        return None


def _watchdog() -> dict | None:
    raw = _read_file("telegram-watchdog-status.json", MAX_JSON_BYTES)
    if not raw:
        return None
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _issue_names(document: dict | None, prefixes: tuple[str, ...]) -> list[str]:
    if not document:
        return []
    names = document.get("issues")
    if not isinstance(names, list):
        return []
    return [n for n in names if isinstance(n, str) and
            len(n) <= 100 and SAFE_SCALAR.fullmatch(n) and n.startswith(prefixes)][:40]


def _watchdog_meta() -> dict:
    doc = _watchdog()
    if not doc:
        return {"available": False, "checked_at": None, "full_check": None}
    checked = doc.get("checkedAt")
    return {"available": True, "checked_at": checked if isinstance(checked,str) and len(checked)<60 else None,
            "full_check": doc.get("fullCheck") is True}


def overview() -> dict:
    names = ("telegram_control_plane_status", "telegram_watchdog_status",
             "rg_telegram_control_app_status", "rg_telegram_control_app_version",
             "last_deploy_status", "deploy_stage", "mcp_deploy_status",
             "telegram_startup_selftest_status", "live_smoke_status")
    return {"source": "Synology read-only state", "data_mode": "local_snapshot",
            "fields": {name: _field(name) for name in names},
            "watchdog": _watchdog_meta(),
            "scheduler_heartbeat_age_sec": _age_seconds("scheduler_last_check_at"),
            "telegram_control_plane_heartbeat_age_sec": _age_seconds("telegram_control_plane_last_sync_at"),
            "note": "UNKNOWN/null means not reported; not proof of OK or failure."}


def scheduler() -> dict:
    names = ("scheduler_last_check_at", "mcp_tick_heartbeat_at",
             "rg_telegram_control_agent_last_run_at", "telegram_control_plane_last_sync_at",
             "failover_heartbeat_at")
    ages = {x: _age_seconds(x) for x in names}
    return {"age_seconds_by_file": ages,
            "scheduler": _field("scheduler_last_check_status"),
            "last_check": _field("last_check_status"),
            "agent_last_action": _field("rg_telegram_control_agent_last_action"),
            "agent_last_rc": _field("rg_telegram_control_agent_last_rc"),
            "nas_scheduler_fresh": ages["scheduler_last_check_at"] is not None and ages["scheduler_last_check_at"] <= 600,
            "note": "Fresh heartbeat does not guarantee Telegram delivery."}


def moderation() -> dict:
    doc = _watchdog()
    return {"watchdog": _watchdog_meta(),
            "watchdog_ok": doc.get("ok") is True if doc else None,
            "issues": _issue_names(doc, ("scanner_", "moderation_", "queue_", "publish_", "publication_", "zero_loss_")),
            "control_agent_last_action": _field("rg_telegram_control_agent_last_action"),
            "command_bus_phase": _field("telegram_command_bus_phase"),
            "command_bus_result": _field("telegram_command_bus_result_status"),
            "note": "Live moderation queue counts are not available from this local snapshot."}


def publications_alerts() -> dict:
    doc = _watchdog()
    minute = doc.get("minuteSilence") if doc else None
    date = dt.datetime.now(TZ).date().isoformat()
    if not isinstance(minute, dict):
        minute = {}
    last_date = minute.get("stateDate")
    if not isinstance(last_date, str) or not re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}", last_date):
        last_date = None
    return {"kyiv_date_today": date,
            "watchdog": _watchdog_meta(),
            "watchdog_issues": _issue_names(doc, ("content_", "publish_", "publication_", "kyiv_alert_", "minute_silence_")),
            "minute_silence": {
                "state_date": last_date if isinstance(last_date, str) else None,
                "matches_today": last_date == date if last_date else None,
                "ledger_status": minute.get("ledgerStatus") if minute.get("ledgerStatus") in ("delivered", "uncertain", "busy", "leased", None) else "unknown",
                "durable_ledger": minute.get("durableLedger") if isinstance(minute.get("durableLedger"), bool) else None,
            },
            "watchdog_status": _field("telegram_watchdog_status"),
            "control_plane_status": _field("telegram_control_plane_status"),
            "note": "This is watchdog evidence, not a live Telegram API publication or alert check."}
