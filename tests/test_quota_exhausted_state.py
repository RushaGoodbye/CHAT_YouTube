from rg_youtube_control.db import connect
from rg_youtube_control.service import (
    YOUTUBE_DAILY_QUOTA_DEFAULT,
    mark_quota_exhausted,
    quota_budget_status,
    today_quota_units,
)


def test_quota_exceeded_sets_authoritative_full_budget(tmp_path):
    conn = connect(tmp_path / "quota-exhausted.sqlite")
    mark_quota_exhausted(conn)

    assert today_quota_units(conn) == YOUTUBE_DAILY_QUOTA_DEFAULT

    budget = quota_budget_status(conn)
    assert budget["exhausted"] is True
    assert budget["used"] == YOUTUBE_DAILY_QUOTA_DEFAULT
    assert budget["remaining"] == 0
    assert budget["spendable"] == 0
    assert budget["reply_capacity"] == 0
    assert budget["video_update_capacity"] == 0
