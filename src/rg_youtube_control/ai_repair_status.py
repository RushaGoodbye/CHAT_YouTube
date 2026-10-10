"""Read-only public GitHub QA status for the *experimental* AI repair pipeline.

Never runs Ollama, applies patches, contacts YouTube, or consumes YouTube quota.
No polling on the UI thread: this module is invoked only by a background worker.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO = "RushaGoodbye/CHAT_YouTube"
ACTIONS_URL = f"https://github.com/{REPO}/actions"
API_URL = f"https://api.github.com/repos/{REPO}/actions/runs"
E2E_PROOF_RUN = 37952330651
E2E_URL = f"{ACTIONS_URL}/runs/{E2E_PROOF_RUN}"
CHECKS = {
    "seo": {
        "branch": "audit/youtube-control-0710-comprehensive-qa",
        "name": "RG YouTube SEO Quality Gate",
    },
    "infra": {
        "branch": "infra/youtube-autofix-sandbox",
        "name": "RG YouTube Repair Infra Check",
    },
}
KNOWN = {"queued", "requested", "waiting", "pending", "in_progress", "completed"}


def _public_json(url: str, *, timeout: float = 7.0) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "RG-YouTube-Control-QA-Status",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        data = response.read(350_000)
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("GitHub API response was not an object")
    return value


def _check_run(raw: dict[str, Any], workflow_name: str) -> dict[str, str]:
    records = raw.get("workflow_runs")
    if not isinstance(records, list):
        raise ValueError("Invalid GitHub workflow list")
    run = next(
        (r for r in records if isinstance(r, dict) and r.get("name") == workflow_name),
        None,
    )
    if run is None:
        return {"state": "NOT_FOUND", "url": ACTIONS_URL, "sha": ""}
    status = str(run.get("status") or "").lower()
    conclusion = str(run.get("conclusion") or "").lower()
    if status == "completed":
        if conclusion == "success":
            state = "PASS"
        elif conclusion in {"failure", "timed_out", "startup_failure"}:
            state = "FAIL"
        elif conclusion in {"cancelled", "skipped", "neutral"}:
            state = "INCOMPLETE"
        else:
            state = "UNKNOWN"
    else:
        state = "RUNNING" if status in KNOWN else "UNKNOWN"
    run_id = run.get("id")
    # Build URLs locally: never open arbitrary URLs supplied by remote JSON.
    url = f"{ACTIONS_URL}/runs/{run_id}" if isinstance(run_id, int) and run_id > 0 else ACTIONS_URL
    return {"state": state, "url": url, "sha": str(run.get("head_sha") or "")[:10]}


def fetch_ai_repair_status(
    loader: Callable[[str], dict[str, Any]] = _public_json,
) -> dict[str, Any]:
    """Query public CI results; status is informative, NOT permission to deploy."""
    checks = {}
    for key, config in CHECKS.items():
        query = urlencode({"branch": config["branch"], "per_page": 15})
        checks[key] = _check_run(loader(f"{API_URL}?{query}"), config["name"])

    # Historical, fixed E2E proof; never confuse with latest release validation.
    proof = loader(f"{API_URL}/{E2E_PROOF_RUN}")
    proof_ok = proof.get("id") == E2E_PROOF_RUN and proof.get("conclusion") == "success" and proof.get("status") == "completed"
    result = {
        "schema": "RG_AI_REPAIR_STATUS_V1",
        "mode": "PILOT_REVIEW_ONLY",
        "auto_apply": False,
        "auto_merge": False,
        "youtube_publication": False,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checks": checks,
        "e2e_proof": {"state": "PASS" if proof_ok else "NOT_CONFIRMED", "url": E2E_URL},
        "actions_url": ACTIONS_URL,
    }
    return result


_STATUS_UK = {
    "PASS": "ПРОЙДЕНО",
    "FAIL": "ПОМИЛКА",
    "INCOMPLETE": "НЕ ЗАВЕРШЕНО",
    "RUNNING": "ВИКОНУЄТЬСЯ",
    "NOT_FOUND": "НЕ ЗНАЙДЕНО",
    "UNKNOWN": "СТАН НЕВІДОМИЙ",
    "NOT_CONFIRMED": "НЕ ПІДТВЕРДЖЕНО",
}


def format_ai_repair_status(status: dict[str, Any]) -> str:
    checks = status.get("checks") or {}
    seo = checks.get("seo") or {}
    infra = checks.get("infra") or {}
    proof = status.get("e2e_proof") or {}
    checked = str(status.get("checked_at") or "").replace("T", " ")[:19]
    return "\n".join([
        "Режим: ТЕСТОВИЙ / ТІЛЬКИ ПЕРЕВІРКА",
        f"SEO Quality Gate: {_STATUS_UK.get(seo.get('state'), 'СТАН НЕВІДОМИЙ')}",
        f"Repair Infra Check: {_STATUS_UK.get(infra.get('state'), 'СТАН НЕВІДОМИЙ')}",
        f"Контрольне AI-виправлення (09.10.2026): {_STATUS_UK.get(proof.get('state'), 'НЕ ПІДТВЕРДЖЕНО')}",
        "Застосування змін: ЗАБОРОНЕНО БЕЗ РУЧНОГО РЕВ'Ю",
        "Публікація YouTube / автоматичне злиття PR: ВИМКНЕНО",
        f"Стан GitHub перевірено (UTC): {checked}",
    ])
