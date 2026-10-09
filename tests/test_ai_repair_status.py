"""Offline tests for the experimental read-only AI repair monitor."""
from __future__ import annotations

from rg_youtube_control.ai_repair_status import (
    ACTIONS_URL, API_URL, E2E_PROOF_RUN, E2E_URL,
    _check_run, fetch_ai_repair_status, format_ai_repair_status,
)


def _run(name, *, id, status="completed", conclusion="success", sha="abc123"):
    return {
        "name": name, "id": id, "status": status,
        "conclusion": conclusion, "head_sha": sha,
        "html_url": "https://other.example.org/untrusted",
    }


def test_public_checks_and_prior_e2e_proof_cannot_authorize_code_changes():
    urls = []
    def loader(url):
        urls.append(url)
        if url.endswith("/" + str(E2E_PROOF_RUN)):
            return {"id": E2E_PROOF_RUN, "status": "completed", "conclusion": "success"}
        if "audit%2Fyoutube" in url:
            return {"workflow_runs": [
                _run("Windows Build", id=2),
                _run("RG YouTube SEO Quality Gate", id=13),
            ]}
        return {"workflow_runs": [_run("RG YouTube Repair Infra Check", id=14)]}
    result = fetch_ai_repair_status(loader)
    assert len(urls) == 3
    assert all(u.startswith(API_URL) for u in urls)
    assert result["mode"] == "PILOT_REVIEW_ONLY"
    assert result["auto_apply"] is False
    assert result["auto_merge"] is False
    assert result["youtube_publication"] is False
    assert result["e2e_proof"] == {"state": "PASS", "url": E2E_URL}
    assert result["checks"]["seo"]["state"] == "PASS"
    assert result["checks"]["infra"]["state"] == "PASS"
    assert result["checks"]["seo"]["url"].startswith(ACTIONS_URL)


def test_latest_relevant_run_is_respected_even_if_failed():
    data = {"workflow_runs": [
        _run("Windows Build", id=99),
        _run("RG YouTube SEO Quality Gate", id=35, conclusion="failure"),
        _run("RG YouTube SEO Quality Gate", id=34),
    ]}
    report = _check_run(data, "RG YouTube SEO Quality Gate")
    assert report["state"] == "FAIL"
    assert report["url"].endswith("/35")


def test_in_progress_and_missing_check_do_not_show_pass():
    waiting = {"workflow_runs": [_run("RG YouTube Repair Infra Check", id=11, status="in_progress", conclusion=None)]}
    assert _check_run(waiting, "RG YouTube Repair Infra Check")["state"] == "RUNNING"
    missing = _check_run(waiting, "RG YouTube SEO Quality Gate")
    assert missing["state"] == "NOT_FOUND"
    assert missing["url"] == ACTIONS_URL


def test_no_untrusted_redirect_url_is_used():
    value = _check_run(
        {"workflow_runs": [_run("RG YouTube SEO Quality Gate", id="https://evil.example")]},
        "RG YouTube SEO Quality Gate",
    )
    assert value["url"] == ACTIONS_URL


def test_status_display_explains_manual_review_and_no_publication():
    result = {
        "checked_at": "2026-10-09T15:00:00+00:00",
        "checks": {"seo": {"state": "PASS"}, "infra": {"state": "RUNNING"}},
        "e2e_proof": {"state": "PASS"},
    }
    text = format_ai_repair_status(result)
    assert "SEO Quality Gate: ПРОЙДЕНО" in text
    assert "Repair Infra Check: ВИКОНУЄТЬСЯ" in text
    assert "РУЧНОГО РЕВ'Ю" in text
    assert "Публікація YouTube" in text
    assert "ВИМКНЕНО" in text


def test_ui_uses_async_readonly_status_worker_no_apply_button():
    from pathlib import Path
    source = (
        Path(__file__).resolve().parents[1]
        / "src/rg_youtube_control/ui.py"
    ).read_text(encoding="utf-8")
    method = source.split("def refresh_ai_repair_status(", 1)[1].split(
        "def refresh_diagnostics_panel(", 1
    )[0]
    assert "LocalToolWorker(fetch_ai_repair_status, self)" in method
    assert "worker.start()" in method
    assert "format_ai_repair_status(result)" in method
    assert "GitHub тимчасово недоступний" in method
    assert "setEnabled(False)" in method
    assert "setEnabled(True)" in method
    assert "Оновити з ZIP" in source  # updater remains separate
    assert "Журнал GitHub / рев'ю патчів" in source
    assert "rg_youtube_seo_repair_agent.py --apply" not in method
