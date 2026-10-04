import inspect

from rg_youtube_control.ui import MainWindow


def test_archive_autorun_has_reentrancy_guard():
    source = inspect.getsource(MainWindow._run_archive_campaign_autorun)

    assert 'getattr(self, "_archive_campaign_autorun_running", False)' in source
    assert "self._archive_campaign_autorun_running = True" in source
    assert "finally:" in source
    assert "self._archive_campaign_autorun_running = False" in source

    guard_pos = source.index(
        'getattr(self, "_archive_campaign_autorun_running", False)'
    )
    step_pos = source.index("run_archive_campaign_step(automatic=True)")
    assert guard_pos < step_pos


def test_safe_archive_checks_full_item_budget_before_metadata_read():
    source = inspect.getsource(MainWindow.apply_next_safe_archive_batch)

    check = 'int(live_budget["campaign_spendable"])'
    assert check in source
    assert 'error_text = "reserve_reached"' in source
    assert source.index(check) < source.index(
        "self._current_video_metadata(video_id)"
    )
