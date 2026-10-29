"""Keep auxiliary startup work out of the first seconds of UI initialization."""
from pathlib import Path
import re


def test_maintenance_is_delayed_past_initial_tables():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    init = source.split("class MainWindow(QMainWindow):", 1)[1].split(
        "    def _startup_load_videos(", 1
    )[0]
    operations = (
        "recover_archive_campaign_state",
        "cleanup_cached_updates",
        "check_for_updates_silent",
        "sync_upcoming_streams_startup",
        "ensure_daily_recovery_backup",
        "check_quota_plan_ready",
        "run_background_maintenance",
        "_resume_saved_workflow",
        "refresh_free_tools_status",
    )
    for operation in operations:
        match = re.search(
            rf"QTimer\.singleShot\((\d+), self\.{operation}\)", init
        )
        assert match, operation
        assert int(match.group(1)) >= 12000, operation
