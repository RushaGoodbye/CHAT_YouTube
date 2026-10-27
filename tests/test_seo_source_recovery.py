"""Wrong NAS transcript never receives a title-only SEO draft.

No network calls, DB writes or source-file mutations in these tests.
"""
import pytest

from rg_youtube_control.seo_source_recovery import validate_or_recover_exact_id_rows


VIDEO_ID = "s3R09Hoocnc"
TITLE = "ІЗРАЇЛЬ — ГЕРОЇ! АЛЕ РОСІЯ ПІДТРИМАЛА ХАМАС"
LOCAL_WRONG = [
    {"text": "Обговорення погоди та шкільних справ у невеликому місті."}
    for _ in range(12)
]
PUBLIC_CORRECT = [
    {"text": "Розмова про Ізраїль, ХАМАС і російську підтримку терористів. "
             "Росіяни дискутують про конфлікт та ізраїльтян."}
    for _ in range(12)
]


def test_matching_local_srt_skips_all_network_and_keeps_original_rows():
    hits = []
    rows, source, recovered = validate_or_recover_exact_id_rows(
        video_id=VIDEO_ID, current_title=TITLE, rows=PUBLIC_CORRECT,
        source_name="nas-exact-video-id",
        fetch_exact_id=lambda vid: hits.append(vid) or LOCAL_WRONG,
    )
    assert rows is PUBLIC_CORRECT
    assert source == "nas-exact-video-id" and not recovered
    assert hits == []


def test_wrong_nas_srt_recovered_only_from_same_video_public_captions():
    hits = []
    rows, source, recovered = validate_or_recover_exact_id_rows(
        video_id=VIDEO_ID, current_title=TITLE, rows=LOCAL_WRONG,
        source_name="nas-exact-video-id",
        fetch_exact_id=lambda vid: hits.append(vid) or PUBLIC_CORRECT,
    )
    assert hits == [VIDEO_ID]
    assert recovered is True
    assert rows is PUBLIC_CORRECT
    assert source == "youtube-exact-id-recovered"
    assert LOCAL_WRONG[0]["text"].startswith("Обговорення погоди")


def test_mismatched_nas_and_mismatched_public_transcript_remain_blocked():
    with pytest.raises(ValueError, match="SEO_SOURCE_IDENTITY_NOT_PROVEN"):
        validate_or_recover_exact_id_rows(
            video_id=VIDEO_ID, current_title=TITLE, rows=LOCAL_WRONG,
            source_name="nas-exact-video-id",
            fetch_exact_id=lambda vid: LOCAL_WRONG,
        )


def test_unavailable_public_captions_fail_closed_without_editing_nas_srt():
    snapshot = tuple(dict(r) for r in LOCAL_WRONG)
    def unavailable(_):
        raise RuntimeError("Captions unavailable")
    with pytest.raises(ValueError, match="SEO_SOURCE_IDENTITY_NOT_PROVEN"):
        validate_or_recover_exact_id_rows(
            video_id=VIDEO_ID, current_title=TITLE, rows=LOCAL_WRONG,
            source_name="nas-exact-video-id",
            fetch_exact_id=unavailable,
        )
    assert tuple(LOCAL_WRONG) == snapshot


def test_ui_checks_exact_source_before_any_timeline_llm():
    from pathlib import Path
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    method = source[source.index("    def _generate_local_seo_result("):
                    source.index("    def _normalize_local_seo_package(")]
    assert method.index("validate_or_recover_exact_id_rows(") < method.index(
        "analyze_all_timeline_blocks("
    )
    assert "fetch_exact_id=fetch_transcript" in method
