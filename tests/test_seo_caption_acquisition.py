import json
from pathlib import Path

from rg_youtube_control.seo_caption_acquisition import (
    acquire_caption_rows, rows_to_srt,
)
from rg_youtube_control.seo_caption_manifest import audit_caption_file

VIDEO_1 = "AbCdEfGh123"
VIDEO_2 = "QwErTyUi456"


def rows(subject="urban transport", count=12):
    return [
        {"text": f"{subject} statement {i}", "start": float(i * 5),
         "duration": 4.0}
        for i in range(count)
    ]


def test_direct_download_creates_matching_manifest(tmp_path):
    result = acquire_caption_rows(
        video_id=VIDEO_1, rows=rows(), duration_s=62, cache_dir=tmp_path,
    )
    assert result["status"] == "NEEDS_REVIEW"
    manifest = json.loads((tmp_path / f"{VIDEO_1}.source.json").read_text())
    assert manifest["video_id"] == VIDEO_1
    assert manifest["acquisition_method"] == "youtube_direct"
    assert audit_caption_file(video_id=VIDEO_1,
        path=tmp_path / f"{VIDEO_1}.srt", duration_s=62)["status"] == "NEEDS_REVIEW"


def test_second_unrelated_video_uses_same_path(tmp_path):
    for video, subject in [(VIDEO_1, "forest fires"), (VIDEO_2, "railway")]:
        result = acquire_caption_rows(
            video_id=video, rows=rows(subject), duration_s=62, cache_dir=tmp_path,
        )
        assert result["status"] == "NEEDS_REVIEW"
    assert len(list(tmp_path.glob("*.source.json"))) == 2


def test_uneven_or_invalid_response_rejected(tmp_path):
    result = acquire_caption_rows(
        video_id=VIDEO_1, rows=rows(count=2), duration_s=62, cache_dir=tmp_path,
    )
    assert result["status"] == "BLOCKED_SOURCE"
    assert not (tmp_path / f"{VIDEO_1}.srt").exists()


def test_invalid_duration_rejected(tmp_path):
    result = acquire_caption_rows(
        video_id=VIDEO_1, rows=rows(), duration_s=0, cache_dir=tmp_path,
    )
    assert result["status"] == "BLOCKED_SOURCE"


def test_corrupt_row_rejected(tmp_path):
    bad = rows()
    bad[2]["duration"] = -1
    result = acquire_caption_rows(
        video_id=VIDEO_1, rows=bad, duration_s=62, cache_dir=tmp_path,
    )
    assert result["status"] == "BLOCKED_SOURCE"


def test_source_response_does_not_overwrite_good_cache_on_failure(tmp_path):
    first = acquire_caption_rows(
        video_id=VIDEO_1, rows=rows(), duration_s=62, cache_dir=tmp_path,
    )
    assert first["status"] == "NEEDS_REVIEW"
    original = (tmp_path / f"{VIDEO_1}.srt").read_bytes()
    second = acquire_caption_rows(
        video_id=VIDEO_1, rows=rows(count=2), duration_s=62, cache_dir=tmp_path,
    )
    assert second["status"] == "BLOCKED_SOURCE"
    assert (tmp_path / f"{VIDEO_1}.srt").read_bytes() == original


def test_tampered_download_file_blocks_later(tmp_path):
    acquire_caption_rows(
        video_id=VIDEO_1, rows=rows(), duration_s=62, cache_dir=tmp_path,
    )
    p = tmp_path / f"{VIDEO_1}.srt"
    p.write_bytes(p.read_bytes() + b"corrupt")
    assert audit_caption_file(video_id=VIDEO_1, path=p, duration_s=62)["status"] == "BLOCKED_SOURCE"


def test_provenance_cannot_be_created_from_invalid_id(tmp_path):
    assert acquire_caption_rows(
        video_id="not-an-id", rows=rows(), duration_s=62, cache_dir=tmp_path,
    )["status"] == "BLOCKED_SOURCE"


def test_srt_round_trip_contains_real_timestamps():
    output = rows_to_srt(rows())
    assert b"00:00:00,000 --> 00:00:04,000" in output
    assert output.count(b"urban transport") == 12
