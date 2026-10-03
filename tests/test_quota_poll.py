import inspect

from rg_youtube_control import main as app_main


def test_archive_campaign_quota_poll_runs_each_minute():
    source = inspect.getsource(app_main.main)
    assert "QTimer(window)" in source
    assert "60 * 1000" in source
    assert "archive_priority_enabled(window.conn)" in source
    assert "window._run_archive_campaign_autorun()" in source
    assert "campaign_timer.start()" in source
