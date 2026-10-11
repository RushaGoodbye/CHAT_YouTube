from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rg_youtube_control.db import connect, set_setting
from rg_youtube_control.vidiq_budget import (
    authorize,
    budget_status,
    record_spend,
    request_fingerprint,
    set_limits,
    set_manual_usage,
    sync_external_balance,
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


def test_vidiq_counter_resets_on_real_billing_date(tmp_path) -> None:
    conn = connect(tmp_path / "rg.db")
    # Use an upcoming billing date: fixed 2026-10-10 went stale on Oct 11,
    # causing sync_external_balance() to advance the real-time cycle before
    # the test could inspect its original balance.
    reset = datetime.now(timezone.utc) + timedelta(days=5)
    sync_external_balance(
        conn,
        max_renewable_credits=2000,
        renewable_credits=1100,
        reset_at=reset.isoformat(),
    )

    before = budget_status(conn, reset - timedelta(hours=1))
    assert before.used == 900
    assert before.remaining == 1100

    after = budget_status(conn, reset + timedelta(hours=1))
    assert after.used == 0
    assert after.remaining == 2000
    assert datetime.fromisoformat(after.reset_at) > reset


def test_vidiq_external_balance_matches_real_bucket_semantics(tmp_path) -> None:
    conn = connect(tmp_path / "rg.db")
    reset = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat().replace("+00:00", "Z")
    status = sync_external_balance(
        conn,
        max_renewable_credits=2000,
        renewable_credits=0,
        reset_at=reset,
        add_on_credits=0,
    )

    assert status.limit == 2000
    assert status.used == 2000
    assert status.remaining == 0
    assert status.reset_at.startswith(reset[:10])
