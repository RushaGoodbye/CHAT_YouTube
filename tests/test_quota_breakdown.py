import inspect

from rg_youtube_control.db import connect
from rg_youtube_control.service import (
    record_quota_units,
    today_quota_breakdown,
    today_quota_units,
)
from rg_youtube_control.ui import MainWindow


def test_quota_breakdown_tracks_video_comments_service(tmp_path):
    conn = connect(tmp_path / "quota-breakdown.sqlite")

    record_quota_units(conn, 51, purpose="video")
    record_quota_units(conn, 5, purpose="comments")
    record_quota_units(conn, 2, purpose="service")

    assert today_quota_units(conn) == 58
    assert today_quota_breakdown(conn) == {
        "video": 51,
        "comments": 5,
        "service": 2,
        "legacy": 0,
        "tracked": 58,
        "used": 58,
    }


def test_quota_breakdown_reports_legacy_unclassified_units(tmp_path):
    from rg_youtube_control.db import set_setting
    from rg_youtube_control.service import current_quota_day

    conn = connect(tmp_path / "quota-legacy.sqlite")
    set_setting(conn, f"youtube_quota_units_{current_quota_day()}", "100")

    record_quota_units(conn, 10, purpose="video")
    breakdown = today_quota_breakdown(conn)

    assert breakdown["used"] == 110
    assert breakdown["video"] == 10
    assert breakdown["legacy"] == 100


def test_quota_label_shows_purpose_breakdown():
    source = inspect.getsource(MainWindow.refresh_youtube_quota_label)

    assert "today_quota_breakdown" in source
    assert "відео" in source
    assert "коментарі" in source
    assert "службове" in source
    assert "до обліку" in source
