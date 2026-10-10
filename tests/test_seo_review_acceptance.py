"""Manual review must be actionable AND never override missing evidence."""
from __future__ import annotations

import json

from rg_youtube_control.seo_review_acceptance import (
    SOURCE_GENERATION,
    load_local_evidence_report,
    reviewed_seo_acceptance_issues,
)


VIDEO_ID = "QCIuLwQm4nU"
VARIANTS = [
    "Заборона пісень у Росії: розмова про цензуру музики",
    "Подорожчання бензину: що відповів російський співрозмовник",
    "Росіянин розповів про цензуру музики й ціни на бензин",
]


def _report():
    return {
        "video_id": VIDEO_ID,
        "blocks_total": 2,
        "blocks_analyzed": 2,
        "blocks_with_evidence": 2,
        "rows_covered": 48,
        "source_rows_total": 48,
        "source_rows_with_text": 48,
        "source_text_chars": 360,
        "covered_text_chars": 360,
        "source_text_sha256": "a" * 64,
        "covered_text_sha256": "a" * 64,
        "source_integrity_verified": True,
        "unverified_blocks": [],
        "needs_review": False,
        "blocks": [
            {"index": 1, "start_stamp": "00:00:00", "verified": True,
             "topics": [{"topic": "Цензура музики",
                         "summary_uk": "Обговорення заборони музики",
                         "evidence": "Забороняють слухати пісні"}]},
            {"index": 2, "start_stamp": "00:15:00", "verified": True,
             "topics": [{"topic": "Ціни на бензин",
                         "summary_uk": "Обговорення вартості пального",
                         "evidence": "Бензин знову подорожчав"}]},
        ],
    }


def _save(tmp_path, report=None):
    path = tmp_path / "seo_evidence"
    path.mkdir(exist_ok=True)
    (path / f"{VIDEO_ID}.json").write_text(
        json.dumps(_report() if report is None else report, ensure_ascii=False),
        encoding="utf-8",
    )


def _check(tmp_path, *, variants=None, description=None, generation=SOURCE_GENERATION, original_description=None):
    return reviewed_seo_acceptance_issues(
        generation=generation,
        video_id=VIDEO_ID,
        title="Цензура музики та ціни на бензин у Росії",
        description=description or (
            "Цензура музики: Забороняють слухати пісні. "
            "Ціни на бензин: Бензин знову подорожчав."
        ),
        variants=VARIANTS if variants is None else variants,
        data_dir=tmp_path,
        original_description=original_description,
    )


def test_fully_evidenced_manually_reviewed_draft_can_reach_ready(tmp_path):
    _save(tmp_path)
    assert load_local_evidence_report(tmp_path, VIDEO_ID)["video_id"] == VIDEO_ID
    assert _check(tmp_path) == []


def test_missing_evidence_stays_blocked_even_after_click(tmp_path):
    assert any("звіт" in item for item in _check(tmp_path))


def test_wrong_video_id_in_report_is_rejected(tmp_path):
    report = _report()
    report["video_id"] = "AAAAAAAAAAA"
    _save(tmp_path, report)
    assert any("звіт" in item for item in _check(tmp_path))


def test_incomplete_or_repeated_ab_titles_cannot_be_approved(tmp_path):
    _save(tmp_path)
    assert _check(tmp_path, variants=VARIANTS[:2])
    assert _check(tmp_path, variants=[VARIANTS[0]] * 3)


def test_unverified_last_block_does_not_become_ready(tmp_path):
    report = _report()
    report["blocks"][1]["topics"] = []
    report["blocks_with_evidence"] = 1
    report["unverified_blocks"] = [2]
    _save(tmp_path, report)
    assert _check(tmp_path)


def test_missing_final_topic_in_description_blocks_approval(tmp_path):
    _save(tmp_path)
    assert any(
        "відсутня" in issue
        for issue in _check(
            tmp_path,
            description="Цензура музики: Забороняють слухати пісні.",
        )
    )


def test_manual_review_must_not_approve_foreign_generation(tmp_path):
    _save(tmp_path)
    assert _check(tmp_path, generation="safe-metadata-0.7.6")


def test_path_traversal_and_invalid_report_are_rejected(tmp_path):
    _save(tmp_path)
    assert load_local_evidence_report(tmp_path, "../oops") is None
    assert load_local_evidence_report(tmp_path, "QCIuLwQm4nU/../") is None
    f = tmp_path / "seo_evidence" / f"{VIDEO_ID}.json"
    f.write_text("{invalid", encoding="utf-8")
    assert _check(tmp_path)


def test_approval_rejects_removed_source_donation_link(tmp_path):
    _save(tmp_path)
    issues = _check(
        tmp_path,
        original_description="Донати: https://donate.rginfoua.pp.ua",
    )
    assert any("втратив посилання" in issue for issue in issues)


def test_approval_keeps_original_links_after_user_edit(tmp_path):
    _save(tmp_path)
    issues = _check(
        tmp_path,
        description=(
            "Цензура музики: Забороняють слухати пісні. "
            "Ціни на бензин: Бензин знову подорожчав. "
            "https://donate.rginfoua.pp.ua"
        ),
        original_description="Донати: https://donate.rginfoua.pp.ua",
    )
    assert not any("втратив посилання" in issue for issue in issues)


def test_approval_rejects_empty_tag_set_when_source_had_tags(tmp_path):
    _save(tmp_path)
    issues = reviewed_seo_acceptance_issues(
        generation=SOURCE_GENERATION,
        video_id=VIDEO_ID,
        title="Цензура музики та ціни на бензин у Росії",
        description=("Цензура музики: Забороняють слухати пісні. "
                     "Ціни на бензин: Бензин знову подорожчав."),
        variants=VARIANTS,
        data_dir=tmp_path,
        original_tags=["чат рулетка"],
        tags=[],
    )
    assert any("усі теги" in issue for issue in issues)
