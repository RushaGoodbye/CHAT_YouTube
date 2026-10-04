import inspect

from rg_youtube_control.ui import MainWindow


def test_scheduled_ready_packages_are_reserved_before_archive():
    source = inspect.getsource(MainWindow._archive_campaign_budget)
    assert "_scheduled_ready_quota_reserve()" in source
    assert "scheduled_reserve" in source
    assert "campaign_spendable" in source
    assert "- scheduled_reserve" in source


def test_scheduled_apply_defines_batch_limit_and_protects_reserve():
    source = inspect.getsource(MainWindow.apply_ready_scheduled_packages)
    assert "batch_limit = reserve_safe_batch_capacity(" in source
    assert 'int(budget["campaign_spendable"])' in source
    assert "rows = rows[:batch_limit]" in source
    assert "SAFE_METADATA_ITEM_COST" in source
    assert "respect_reserve=True" in source
    assert "scheduled_publish_at" in source
    assert "privacy_status" not in source[source.index("_quota_update_video_with_client"):]


def test_safe_archive_uses_budget_after_scheduled_reservation():
    source = inspect.getsource(MainWindow.apply_next_safe_archive_batch)
    assert "budget = self._archive_campaign_budget()" in source
    assert 'live_budget = self._archive_campaign_budget()' in source
