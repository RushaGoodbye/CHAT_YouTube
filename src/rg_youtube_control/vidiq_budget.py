from __future__ import annotations

import calendar
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .db import get_setting, set_setting

VIDIQ_MONTHLY_CREDITS_DEFAULT = 2000
VIDIQ_RESERVE_CREDITS_DEFAULT = 300
VIDIQ_PLAN_NAME = "AIR Boost"

PRIORITY_CATEGORIES = {
    "scheduled",
    "new_publish",
    "archive_top",
    "title_final",
}

LOCAL_ONLY_CATEGORIES = {
    "archive_bulk",
    "description_bulk",
    "tags_bulk",
    "comments_bulk",
}


@dataclass(frozen=True)
class VidIQBudget:
    period: str
    plan: str
    limit: int
    used: int
    remaining: int
    reserve: int
    spendable: int
    reset_at: str
    add_on_credits: int


@dataclass(frozen=True)
class VidIQDecision:
    allowed: bool
    reason: str
    duplicate: bool
    budget: VidIQBudget


def _parse_dt(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _add_one_month(value: datetime) -> datetime:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _ensure_cycle(conn, now: datetime | None = None) -> tuple[str, str]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    reset_raw = get_setting(conn, "vidiq_reset_at", "")
    reset = _parse_dt(reset_raw)

    if reset is not None and current >= reset:
        while current >= reset:
            reset = _add_one_month(reset)
        set_setting(conn, "vidiq_used_credits", "0")
        set_setting(conn, "vidiq_add_on_credits", "0")
        set_setting(conn, "vidiq_request_ledger", "[]")
        reset_raw = reset.isoformat()
        set_setting(conn, "vidiq_reset_at", reset_raw)

    if reset is not None:
        period = f"до {reset.astimezone(timezone.utc).strftime('%Y-%m-%d')}"
        return period, reset.isoformat()

    # Until the exact vidIQ billing reset is synced, do not invent a calendar
    # reset. The counter stays persistent and can be aligned manually.
    period = get_setting(conn, "vidiq_credit_period", "поточний цикл")
    if not period:
        period = "поточний цикл"
    return period, reset_raw


def budget_status(conn, now: datetime | None = None) -> VidIQBudget:
    period, reset_at = _ensure_cycle(conn, now)
    limit = max(
        1,
        int(
            get_setting(
                conn,
                "vidiq_monthly_limit",
                str(VIDIQ_MONTHLY_CREDITS_DEFAULT),
            )
            or VIDIQ_MONTHLY_CREDITS_DEFAULT
        ),
    )
    reserve = max(
        0,
        min(
            limit,
            int(
                get_setting(
                    conn,
                    "vidiq_reserve_credits",
                    str(VIDIQ_RESERVE_CREDITS_DEFAULT),
                )
                or VIDIQ_RESERVE_CREDITS_DEFAULT
            ),
        ),
    )
    used = max(0, min(limit, int(get_setting(conn, "vidiq_used_credits", "0") or 0)))
    add_on = max(0, int(get_setting(conn, "vidiq_add_on_credits", "0") or 0))
    renewable_remaining = max(0, limit - used)
    remaining = renewable_remaining + add_on
    spendable = max(0, remaining - reserve)
    return VidIQBudget(
        period=period,
        plan=get_setting(conn, "vidiq_plan_name", VIDIQ_PLAN_NAME) or VIDIQ_PLAN_NAME,
        limit=limit,
        used=used,
        remaining=remaining,
        reserve=reserve,
        spendable=spendable,
        reset_at=reset_at,
        add_on_credits=add_on,
    )


def sync_external_balance(
    conn,
    *,
    max_renewable_credits: int,
    renewable_credits: int,
    reset_at: str,
    add_on_credits: int = 0,
    plan: str = VIDIQ_PLAN_NAME,
) -> VidIQBudget:
    limit = max(1, int(max_renewable_credits))
    renewable = max(0, min(limit, int(renewable_credits)))
    used = max(0, limit - renewable)
    set_setting(conn, "vidiq_plan_name", str(plan or VIDIQ_PLAN_NAME))
    set_setting(conn, "vidiq_monthly_limit", str(limit))
    set_setting(conn, "vidiq_used_credits", str(used))
    set_setting(conn, "vidiq_add_on_credits", str(max(0, int(add_on_credits))))
    if str(reset_at or "").strip():
        set_setting(conn, "vidiq_reset_at", str(reset_at).strip())
        set_setting(
            conn,
            "vidiq_credit_period",
            f"до {str(reset_at).strip()[:10]}",
        )
    return budget_status(conn)


def set_manual_usage(conn, used: int) -> VidIQBudget:
    status = budget_status(conn)
    value = max(0, min(int(used), status.limit))
    set_setting(conn, "vidiq_used_credits", str(value))
    return budget_status(conn)


def set_limits(conn, *, limit: int, reserve: int) -> VidIQBudget:
    limit_value = max(1, int(limit))
    reserve_value = max(0, min(int(reserve), limit_value))
    set_setting(conn, "vidiq_monthly_limit", str(limit_value))
    set_setting(conn, "vidiq_reserve_credits", str(reserve_value))
    current_used = int(get_setting(conn, "vidiq_used_credits", "0") or 0)
    if current_used > limit_value:
        set_setting(conn, "vidiq_used_credits", str(limit_value))
    return budget_status(conn)


def request_fingerprint(
    *,
    category: str,
    video_id: str = "",
    payload: str = "",
) -> str:
    raw = "\n".join(
        (
            str(category or "").strip().casefold(),
            str(video_id or "").strip(),
            str(payload or "").strip(),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ledger(conn) -> list[dict[str, Any]]:
    try:
        value = json.loads(get_setting(conn, "vidiq_request_ledger", "[]") or "[]")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return []


def _is_duplicate(conn, fingerprint: str) -> bool:
    if not fingerprint:
        return False
    return any(
        str(item.get("fingerprint") or "") == fingerprint
        for item in _ledger(conn)
    )


def authorize(
    conn,
    *,
    credits: int,
    category: str,
    fingerprint: str = "",
) -> VidIQDecision:
    status = budget_status(conn)
    cost = max(0, int(credits))
    kind = str(category or "").strip().casefold()

    if kind in LOCAL_ONLY_CATEGORIES:
        return VidIQDecision(False, "bulk_local_only", False, status)
    if fingerprint and _is_duplicate(conn, fingerprint):
        return VidIQDecision(False, "duplicate_request", True, status)
    if cost > status.remaining:
        return VidIQDecision(False, "billing_cycle_limit", False, status)
    if kind not in PRIORITY_CATEGORIES and cost > status.spendable:
        return VidIQDecision(False, "reserve_protected", False, status)
    return VidIQDecision(True, "ok", False, status)


def record_spend(
    conn,
    *,
    credits: int,
    category: str,
    fingerprint: str = "",
    video_id: str = "",
    note: str = "",
) -> VidIQBudget:
    decision = authorize(
        conn,
        credits=credits,
        category=category,
        fingerprint=fingerprint,
    )
    if not decision.allowed:
        raise RuntimeError(f"vidIQ request blocked: {decision.reason}")

    cost = max(0, int(credits))
    renewable_remaining = max(0, decision.budget.limit - decision.budget.used)
    renewable_spend = min(cost, renewable_remaining)
    add_on_spend = max(0, cost - renewable_spend)
    new_used = min(decision.budget.limit, decision.budget.used + renewable_spend)
    set_setting(conn, "vidiq_used_credits", str(new_used))
    if add_on_spend:
        set_setting(
            conn,
            "vidiq_add_on_credits",
            str(max(0, decision.budget.add_on_credits - add_on_spend)),
        )

    if fingerprint:
        ledger = _ledger(conn)
        ledger.append(
            {
                "fingerprint": fingerprint,
                "category": str(category or ""),
                "video_id": str(video_id or ""),
                "credits": cost,
                "note": str(note or ""),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        set_setting(
            conn,
            "vidiq_request_ledger",
            json.dumps(ledger[-500:], ensure_ascii=False),
        )
    return budget_status(conn)


def policy_summary() -> str:
    return (
        "vidIQ: лише заплановані/нові публікації, ТОП архіву та фінальна "
        "перевірка назв. Масовий архів, описи, теги й коментарі - локально."
    )
