from __future__ import annotations

from datetime import datetime, timezone

from rg_youtube_control.db import connect, set_setting
from rg_youtube_control.vidiq_budget import (
    authorize,
    budget_status,
    record_spend,
    request_fingerprint,
    set_limits,
    set_manual_usage,
)


def test_vidiq_budget_is_shared_and_protects_reserve(tmp_path) -> None:
    conn = connect(tmp_path / "rg.db")
    set_limits(conn, limit=2000, reserve=300)
    set_manual_usage(conn, 1600)

    status = budget_status(conn)
    assert status.limit == 2000
    assert status.used == 1600
    assert status.remaining == 400
    assert status.spendable == 100

    normal = authorize(conn, credits=150, category="other")
    assert not normal.allowed
    assert normal.reason == "reserve_protected"

    priority = authorize(conn, credits=150, category="scheduled")
    assert priority.allowed


def test_vidiq_bulk_categories_are_local_only(tmp_path) -> None:
    conn = connect(tmp_path / "rg.db")
    set_limits(conn, limit=2000, reserve=300)

    decision = authorize(conn, credits=1, category="archive_bulk")
    assert not decision.allowed
    assert decision.reason == "bulk_local_only"


def test_vidiq_duplicate_request_is_blocked(tmp_path) -> None:
    conn = connect(tmp_path / "rg.db")
    set_limits(conn, limit=2000, reserve=300)

    fingerprint = request_fingerprint(
        category="title_final",
        video_id="video1",
        payload="candidate title",
    )
    record_spend(
        conn,
        credits=10,
        category="title_final",
        fingerprint=fingerprint,
        video_id="video1",
    )

    duplicate = authorize(
        conn,
        credits=10,
        category="title_final",
        fingerprint=fingerprint,
    )
    assert not duplicate.allowed
    assert duplicate.duplicate
    assert duplicate.reason == "duplicate_request"


def test_vidiq_counter_resets_on_new_month(tmp_path) -> None:
    conn = connect(tmp_path / "rg.db")
    set_setting(conn, "vidiq_monthly_limit", "2000")
    set_setting(conn, "vidiq_reserve_credits", "300")
    set_setting(conn, "vidiq_credit_period", "2026-09")
    set_setting(conn, "vidiq_used_credits", "900")

    october = budget_status(
        conn,
        datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
    )
    assert october.period == "2026-10"
    assert october.used == 0
