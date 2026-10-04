import inspect

from rg_youtube_control.service import (
    QUOTA_RESERVE_DEFAULT,
    reserve_safe_daily_batch_capacity,
)
from rg_youtube_control.ui import MainWindow


def test_archive_default_reserve_is_small_and_video_first():
    assert QUOTA_RESERVE_DEFAULT == 500
    assert reserve_safe_daily_batch_capacity(9500, 500) == 186


def test_daily_safe_batch_prefetches_metadata_in_batches():
    source = inspect.getsource(MainWindow.apply_next_safe_archive_batch)

    assert "video_details_with_request_count" in source
    assert "prefetched_metadata" in source
    assert "metadata_reads = refresh_reads if daily else len(video_ids)" in source
    assert "VIDEO_UPDATE_COST" in source
    assert "self._current_video_metadata(" in source
    assert "if daily:" in source


def test_archive_priority_throttles_background_comment_scans():
    source = inspect.getsource(MainWindow.background_scan_all_channels)

    assert "_archive_campaign_autorun_running" in source
    assert "archive_priority_comment_scan_last" in source
    assert "30 * 60" in source
    assert "archive_priority_enabled(self.conn)" in source
